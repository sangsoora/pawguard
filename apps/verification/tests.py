import json
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import AuditLog
from apps.verification import provider, services, signing
from apps.verification.models import VerificationCase, VerificationEvent, WebhookEvent
from apps.verification.tasks import send_to_provider

S = VerificationCase.State
SECRET = "test-webhook-secret"
URL = "/api/verification/webhook/"
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "provider_webhook.schema.json").read_text())


@pytest.fixture
def user(db):
    return User.objects.create_user("sitter", "s@x.com", "pw", role=User.Role.SITTER)


@pytest.fixture
def agent(db):
    return User.objects.create_user("agent", "a@x.com", "pw", role=User.Role.AGENT)


@pytest.fixture
def submitted(user):
    case = services.submit_documents(
        user, full_name="Ana García", document_number="X1234567Z", document_country="es"
    )
    send_to_provider(case.pk)
    case.refresh_from_db()
    return case


def post_event(payload, *, secret=SECRET, header=None, client=None):
    body = json.dumps(payload).encode()
    sig = header if header is not None else signing.sign(secret, body)
    return (client or Client()).post(
        URL, data=body, content_type="application/json", HTTP_X_PROVIDER_SIGNATURE=sig
    )


# --- signatures ---


def test_sign_and_verify_roundtrip():
    body = b'{"a":1}'
    signing.verify(SECRET, body, signing.sign(SECRET, body))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body, h: (b'{"a":2}', h),  # tampered body
        lambda body, h: (body, h.replace("v1=", "v1=0")),  # tampered signature
        lambda body, h: (body, "garbage"),  # malformed
        lambda body, h: (body, ""),  # missing
    ],
)
def test_verify_rejects_bad_signatures(mutate):
    body = b'{"a":1}'
    body2, header = mutate(body, signing.sign(SECRET, body))
    with pytest.raises(signing.InvalidSignature):
        signing.verify(SECRET, body2, header)


def test_verify_rejects_replay_outside_tolerance_and_empty_secret():
    body = b"{}"
    old = signing.sign(SECRET, body, timestamp=1_000_000)
    with pytest.raises(signing.InvalidSignature, match="tolerance"):
        signing.verify(SECRET, body, old, now=1_000_000 + signing.TOLERANCE_SECONDS + 1)
    with pytest.raises(signing.InvalidSignature, match="not configured"):
        signing.verify("", body, signing.sign("", body))  # fail closed


# --- contract tests ---


@pytest.mark.parametrize("name", ["approved.json", "rejected.json"])
def test_contract_examples_conform_to_schema(name):
    jsonschema.validate(json.loads((CONTRACTS / "examples" / name).read_text()), SCHEMA)


@pytest.mark.parametrize(
    "event_type", ["verification.approved", "verification.rejected", "verification.needs_review"]
)
def test_provider_emits_contract_conformant_events(event_type):
    """Provider side of the contract: whatever the mock sends must validate."""
    jsonschema.validate(provider.build_event(event_type, "ref_1", reason="why"), SCHEMA)


@pytest.mark.parametrize(
    "broken",
    [
        {"type": "verification.approved", "created": 1, "data": {"reference": "r"}},  # no id
        {"id": "e", "type": "verification.exploded", "created": 1, "data": {"reference": "r"}},
        {"id": "e", "type": "verification.approved", "created": "now", "data": {"reference": "r"}},
        {"id": "e", "type": "verification.approved", "created": 1, "data": {}},  # no reference
        {
            "id": "e",
            "type": "verification.approved",
            "created": 1,
            "data": {"reference": "r"},
            "extra": 1,
        },  # fmt: skip
    ],
)
def test_consumer_rejects_payloads_that_break_the_contract(db, broken):
    """Consumer side: PawGuard refuses anything off-contract, with a signature that is valid."""
    r = post_event(broken)
    assert r.status_code == 400
    assert not WebhookEvent.objects.exists()


# --- webhook endpoint ---


def event(case, type_="verification.approved", **kw):
    return provider.build_event(type_, case.provider_ref, **kw)


def test_webhook_rejects_unsigned_and_wrongly_signed(submitted):
    payload = event(submitted)
    assert post_event(payload, secret="wrong").status_code == 401
    assert post_event(payload, header="").status_code == 401
    assert Client().get(URL).status_code == 405
    submitted.refresh_from_db()
    assert submitted.state == S.SUBMITTED  # nothing applied


def test_webhook_applies_approval_and_records_audit_trail(submitted):
    r = post_event(event(submitted))
    assert (r.status_code, r.json()) == (200, {"status": "applied"})
    submitted.refresh_from_db()
    assert submitted.state == S.VERIFIED and submitted.decided_at
    trail = list(submitted.events.values_list("from_state", "to_state", "source"))
    assert trail == [("requested", "submitted", "user"), ("submitted", "verified", "provider")]


def test_webhook_is_idempotent_on_event_id(submitted):
    payload = event(submitted, "verification.rejected", reason="Document expired")
    assert post_event(payload).json() == {"status": "applied"}
    assert post_event(payload).json() == {"status": "duplicate"}  # provider retry
    assert post_event(payload).json() == {"status": "duplicate"}
    submitted.refresh_from_db()
    assert submitted.state == S.REJECTED and submitted.rejection_reason == "Document expired"
    assert submitted.events.count() == 2  # no extra transitions
    assert WebhookEvent.objects.count() == 1


def test_out_of_order_event_is_acknowledged_but_ignored(submitted):
    assert post_event(event(submitted)).json() == {"status": "applied"}  # now verified
    late = event(submitted, "verification.rejected")  # a different, late event
    assert post_event(late).json() == {"status": "ignored"}
    submitted.refresh_from_db()
    assert submitted.state == S.VERIFIED
    assert WebhookEvent.objects.get(event_id=late["id"]).outcome == "ignored"


def test_unknown_reference_is_acknowledged(db):
    r = post_event(provider.build_event("verification.approved", "mock_nope"))
    assert r.json() == {"status": "unknown_case"}


def test_needs_review_then_agent_decides(submitted):
    assert post_event(event(submitted, "verification.needs_review")).json()["status"] == "applied"
    submitted.refresh_from_db()
    assert submitted.state == S.MANUAL_REVIEW


# --- state machine ---


def test_illegal_transitions_are_refused(user):
    case = VerificationCase.objects.create(user=user)
    with pytest.raises(services.InvalidTransition):
        services.transition(case, S.VERIFIED, source="agent")  # cannot skip submission
    case = services.transition(case, S.SUBMITTED, source="user")
    case = services.transition(case, S.REJECTED, source="provider", detail="bad")
    with pytest.raises(services.InvalidTransition):
        services.transition(case, S.VERIFIED, source="agent")  # terminal state


# --- PII ---


def test_pii_is_encrypted_at_rest_and_decrypted_by_the_orm(submitted):
    with connection.cursor() as cursor:
        cursor.execute(
            "select full_name, document_number from verification_verificationcase where id=%s",
            [submitted.pk],
        )
        raw_name, raw_doc = cursor.fetchone()
    assert "Ana" not in raw_name and "X1234567Z" not in raw_doc  # ciphertext in the database
    fresh = VerificationCase.objects.get(pk=submitted.pk)
    assert (fresh.full_name, fresh.document_number) == ("Ana García", "X1234567Z")
    assert fresh.document_country == "ES"


def test_key_rotation_old_rows_still_decrypt(submitted, settings):
    from cryptography.fernet import Fernet

    new_key = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEYS = [new_key, *settings.FIELD_ENCRYPTION_KEYS]
    assert VerificationCase.objects.get(pk=submitted.pk).document_number == "X1234567Z"
    settings.FIELD_ENCRYPTION_KEYS = [new_key]  # old key dropped without re-saving
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured):
        VerificationCase.objects.get(pk=submitted.pk)


def test_retention_purges_pii_but_keeps_case_and_trail(submitted):
    post_event(event(submitted))
    old = timezone.now() - timedelta(days=45)
    VerificationCase.objects.filter(pk=submitted.pk).update(decided_at=old)
    fresh_open = services.submit_documents(
        User.objects.create_user("other", "o@x.com", "pw", role=User.Role.OWNER),
        full_name="Open Case",
        document_number="ZZ9999",
        document_country="FR",
    )

    assert services.purge_expired_documents(days=30) == 1
    case = VerificationCase.objects.get(pk=submitted.pk)
    assert (case.full_name, case.document_number) == ("", "") and case.purged_at
    assert case.state == S.VERIFIED  # decision survives
    assert case.events.filter(source="system").exists()  # purge is itself audited
    assert VerificationCase.objects.get(pk=fresh_open.pk).full_name == "Open Case"
    assert services.purge_expired_documents(days=30) == 0  # idempotent


# --- submission API + provider task ---


def api_client(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


def test_user_submits_documents(user, django_capture_on_commit_callbacks):
    payload = {"full_name": "Ana García", "document_number": "X1234567Z", "document_country": "es"}
    with django_capture_on_commit_callbacks(execute=True):
        r = api_client(user).post("/api/verification/me/", payload)
    assert r.status_code == 202
    assert r.json()["state"] == "submitted" and r.json()["can_submit"] is False
    case = user.verification_cases.get()
    assert case.provider_ref and case.provider_ref.startswith("mock_")  # sent to the provider
    me = api_client(user).get("/api/verification/me/").json()
    assert me["state"] == "submitted"
    assert "X1234567Z" not in json.dumps(me) and "Ana" not in json.dumps(me)  # no PII


@pytest.mark.parametrize(
    "bad",
    [
        {"full_name": "A", "document_number": "X1234567Z", "document_country": "ES"},
        {"full_name": "Ana", "document_number": "no spaces!", "document_country": "ES"},
        {"full_name": "Ana", "document_number": "X1234567Z", "document_country": "ESP"},
    ],
)
def test_submission_validation(user, bad):
    assert api_client(user).post("/api/verification/me/", bad).status_code == 400


def test_cannot_submit_twice_or_after_verified(submitted):
    payload = {"full_name": "Ana García", "document_number": "X1234567Z", "document_country": "ES"}
    assert api_client(submitted.user).post("/api/verification/me/", payload).status_code == 409
    post_event(event(submitted))
    r = api_client(submitted.user).post("/api/verification/me/", payload)
    assert r.status_code == 409 and "already verified" in r.json()["detail"]


def test_agents_and_anonymous_cannot_use_user_endpoint(agent):
    assert api_client(agent).get("/api/verification/me/").status_code == 403
    assert APIClient().get("/api/verification/me/").status_code in (401, 403)


def test_provider_send_is_idempotent_and_survives_outage(user, monkeypatch):
    case = services.submit_documents(
        user, full_name="Ana García", document_number="X1234567Z", document_country="ES"
    )

    class Down:
        def submit(self, case):
            raise provider.ProviderError("provider down")

    monkeypatch.setattr("apps.verification.tasks.get_provider", lambda: Down())
    with pytest.raises(provider.ProviderError):
        send_to_provider(case.pk)
    case.refresh_from_db()
    assert case.provider_ref is None and case.state == S.SUBMITTED  # retryable

    monkeypatch.undo()
    ref = send_to_provider(case.pk)
    assert ref and send_to_provider(case.pk) == ref  # second call does not re-send


def test_failed_provider_does_not_fail_the_users_request(
    user, monkeypatch, django_capture_on_commit_callbacks
):
    class Down:
        def submit(self, case):
            raise provider.ProviderError("provider down")

    monkeypatch.setattr("apps.verification.tasks.get_provider", lambda: Down())
    payload = {"full_name": "Ana García", "document_number": "X1234567Z", "document_country": "ES"}
    with django_capture_on_commit_callbacks(execute=True):
        r = api_client(user).post("/api/verification/me/", payload)
    assert r.status_code == 202  # accepted; sending can be retried


# --- console ---

BASE = "/api/console"


def test_agent_requests_verification_then_user_submits(
    agent, user, django_capture_on_commit_callbacks
):
    c = api_client(agent)
    r = c.post(f"{BASE}/users/{user.pk}/request-verification/")
    assert r.status_code == 200 and r.json()["verification_state"] == "requested"
    assert c.post(f"{BASE}/users/{user.pk}/request-verification/").status_code == 409
    assert AuditLog.objects.get().action == "user.request_verification"

    payload = {"full_name": "Ana García", "document_number": "X1234567Z", "document_country": "ES"}
    with django_capture_on_commit_callbacks(execute=True):
        assert api_client(user).post("/api/verification/me/", payload).status_code == 202
    case = user.verification_cases.get()  # the agent's request was reused, not duplicated
    assert case.requested_by == agent and case.state == S.SUBMITTED


def test_agents_cannot_be_asked_to_verify(agent):
    other = User.objects.create_user("agent2", "a2@x.com", "pw", role=User.Role.AGENT)
    assert (
        api_client(agent).post(f"{BASE}/users/{other.pk}/request-verification/").status_code == 403
    )


def test_manual_review_queue_masks_document_and_agent_decides(agent, submitted):
    post_event(event(submitted, "verification.needs_review"))
    c = api_client(agent)
    data = c.get(f"{BASE}/verifications/?state=manual_review").json()
    assert data["count"] == 1
    item = data["results"][0]
    assert item["document_number_masked"] == "\u2022" * 5 + "567Z"
    assert "X1234567Z" not in json.dumps(item)  # the full number never leaves the server

    url = f"{BASE}/verifications/{submitted.pk}"
    assert c.post(f"{url}/reject/", {}).status_code == 400  # reason required
    r = c.post(f"{url}/approve/", {"reason": "Documents match profile"})
    assert r.status_code == 200 and r.json()["state"] == "verified"
    assert c.post(f"{url}/reject/", {"reason": "again"}).status_code == 409  # already decided
    log = AuditLog.objects.get()
    assert (log.action, log.target_type, log.metadata["reason"]) == (
        "verification.verified",
        "verification",
        "Documents match profile",
    )
    assert VerificationEvent.objects.filter(source="agent", actor_label="agent").exists()


def test_agent_cannot_decide_a_case_that_is_not_in_manual_review(agent, submitted):
    r = api_client(agent).post(f"{BASE}/verifications/{submitted.pk}/approve/", {"reason": "x"})
    assert r.status_code == 409
    submitted.refresh_from_db()
    assert submitted.state == S.SUBMITTED


def test_console_users_show_verification_state(agent, submitted):
    row = api_client(agent).get(f"{BASE}/users/?search=sitter").json()["results"][0]
    assert row["verification_state"] == "submitted"


def test_verification_console_requires_agent(user, submitted):
    assert api_client(user).get(f"{BASE}/verifications/").status_code == 403


def test_simulate_command_requires_provider_reference(db, user):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    case = VerificationCase.objects.create(user=user)
    with pytest.raises(CommandError, match="provider reference"):
        call_command("simulate_provider_webhook", case.pk, "approved")


# --- user-facing status payload ---


def test_status_payload_for_each_situation(user, agent):
    c = api_client(user)
    assert c.get("/api/verification/me/").json() == {
        "state": "none",
        "can_submit": True,
        "rejection_reason": "",
        "requested_by_agent": False,
    }
    case = services.request_verification(user, agent=agent)
    asked = c.get("/api/verification/me/").json()
    assert asked["state"] == "requested" and asked["requested_by_agent"] and asked["can_submit"]

    services.transition(case, S.SUBMITTED, source="user")
    services.transition(case, S.REJECTED, source="provider", detail="Document expired")
    rejected = c.get("/api/verification/me/").json()
    assert rejected["state"] == "rejected" and rejected["can_submit"] is True
    assert rejected["rejection_reason"] == "Document expired"  # they are told why


def test_user_can_resubmit_after_rejection(user):
    case = services.submit_documents(
        user, full_name="Ana García", document_number="X1234567Z", document_country="ES"
    )
    services.transition(case, S.REJECTED, source="provider", detail="Blurry photo")
    payload = {"full_name": "Ana García", "document_number": "X7654321Z", "document_country": "ES"}
    r = api_client(user).post("/api/verification/me/", payload)
    assert r.status_code == 202 and user.verification_cases.count() == 2


# --- re-send sweeper ---


def _stuck_case(user, *, age_seconds=600, number="X1234567Z"):
    case = services.submit_documents(
        user, full_name="Ana García", document_number=number, document_country="ES"
    )
    VerificationCase.objects.filter(pk=case.pk).update(
        submitted_at=timezone.now() - timedelta(seconds=age_seconds)
    )
    return case


def test_sweeper_resends_stuck_submissions(user):
    from apps.verification.tasks import resend_unsent

    case = _stuck_case(user)
    assert resend_unsent(min_age_seconds=120) == {"found": 1, "sent": 1, "failed": 0}
    case.refresh_from_db()
    assert case.provider_ref and case.provider_ref.startswith("mock_")
    assert resend_unsent(min_age_seconds=120)["found"] == 0  # nothing left to do


def test_sweeper_leaves_fresh_sent_and_decided_cases_alone(user, agent):
    from apps.verification.tasks import resend_unsent

    fresh = _stuck_case(user, age_seconds=10)  # still being sent normally
    other = User.objects.create_user("o2", "o2@x.com", "pw", role=User.Role.OWNER)
    sent = _stuck_case(other, number="AB123456")
    send_to_provider(sent.pk)  # already has a reference
    third = User.objects.create_user("o3", "o3@x.com", "pw", role=User.Role.OWNER)
    decided = _stuck_case(third, number="CD123456")
    services.transition(decided, S.REJECTED, source="provider", detail="x")

    assert resend_unsent(min_age_seconds=120)["found"] == 0
    fresh.refresh_from_db()
    assert fresh.provider_ref is None


def test_one_failing_case_does_not_block_the_others(user, monkeypatch):
    from apps.verification.tasks import resend_unsent

    first = _stuck_case(user)
    other = User.objects.create_user("o2", "o2@x.com", "pw", role=User.Role.OWNER)
    second = _stuck_case(other, number="AB123456")
    real = provider.MockProvider.submit

    def flaky(self, case):
        if case.pk == first.pk:
            raise provider.ProviderError("down")
        return real(self, case)

    monkeypatch.setattr(provider.MockProvider, "submit", flaky)
    assert resend_unsent(min_age_seconds=120) == {"found": 2, "sent": 1, "failed": 1}
    first.refresh_from_db(), second.refresh_from_db()
    assert first.provider_ref is None and second.provider_ref  # first stays retryable
    monkeypatch.undo()
    assert resend_unsent(min_age_seconds=120)["sent"] == 1  # next sweep picks it up


def test_sweeper_updates_metrics_and_gauges(user):
    from apps.core import metrics
    from apps.verification.tasks import resend_unsent

    _stuck_case(user, age_seconds=1800)
    assert metrics.registry.get_sample_value("pawguard_verification_unsent_cases") == 1
    age = metrics.registry.get_sample_value("pawguard_verification_unsent_oldest_age_seconds")
    assert age >= 1790
    before = (
        metrics.registry.get_sample_value("pawguard_verification_resend_total", {"outcome": "sent"})
        or 0
    )
    resend_unsent(min_age_seconds=120)
    after = metrics.registry.get_sample_value(
        "pawguard_verification_resend_total", {"outcome": "sent"}
    )
    assert after == before + 1
    assert metrics.registry.get_sample_value("pawguard_verification_unsent_cases") == 0


def test_sweeper_is_scheduled_and_has_a_command(user, settings):
    from django.core.management import call_command

    assert settings.CELERY_BEAT_SCHEDULE["resend-unsent-verifications"]["task"] == (
        "apps.verification.tasks.resend_unsent_task"
    )
    _stuck_case(user)
    call_command("resend_unsent_verifications", "--min-age", "120")
    assert user.verification_cases.get().provider_ref
