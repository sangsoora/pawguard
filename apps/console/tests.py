from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.core.models import AuditLog
from apps.risk.engine import score_booking
from apps.risk.models import RiskAssessment

BASE = "/api/console"


@pytest.fixture
def agent(db):
    return User.objects.create_user("agent", "a@x.com", "pw", role=User.Role.AGENT)


@pytest.fixture
def api(agent):
    client = APIClient()
    client.force_authenticate(agent)
    return client


@pytest.fixture
def owner(db):
    return User.objects.create_user("owner", "o@x.com", "pw", role=User.Role.OWNER)


@pytest.fixture
def sitter(db):
    return User.objects.create_user("sitter", "s@x.com", "pw", role=User.Role.SITTER)


@pytest.fixture
def flagged(owner, sitter):
    """A booking that scores 40 (review) via NEW_ACCOUNT_HIGH_VALUE."""
    b = Booking.objects.create(
        owner=owner,
        sitter=sitter,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        amount=Decimal("900.00"),
    )
    return score_booking(b)


# --- access control ---


@pytest.mark.parametrize("path", ["/assessments/", "/users/", "/audit/"])
def test_anonymous_is_rejected(db, path):
    assert APIClient().get(BASE + path).status_code in (401, 403)


def test_non_agents_are_forbidden(owner):
    client = APIClient()
    client.force_authenticate(owner)
    assert client.get(f"{BASE}/assessments/").status_code == 403


# --- assessments ---


def test_list_includes_hits_and_sorts_by_score(api, flagged, owner, sitter):
    low = Booking.objects.create(
        owner=owner,
        sitter=sitter,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        amount=Decimal("20.00"),
    )
    score_booking(low)
    data = api.get(f"{BASE}/assessments/").json()
    assert [r["score"] for r in data["results"]] == [40, 0]
    top = data["results"][0]
    assert top["hits"][0]["reason_code"] == "NEW_ACCOUNT_HIGH_VALUE"
    assert top["booking"]["sitter"] == "sitter"


def test_filters(api, flagged):
    assert api.get(f"{BASE}/assessments/?decision=review").json()["count"] == 1
    assert api.get(f"{BASE}/assessments/?decision=block").json()["count"] == 0
    assert api.get(f"{BASE}/assessments/?min_score=41").json()["count"] == 0
    assert api.get(f"{BASE}/assessments/?review_status=pending").json()["count"] == 1
    assert api.get(f"{BASE}/assessments/?ordering=;drop").status_code == 200  # ignored


def test_review_clears_and_audits(api, agent, flagged):
    r = api.post(f"{BASE}/assessments/{flagged.pk}/review/", {"outcome": "cleared"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "cleared"
    assert r.json()["reviewed_by"] == "agent"
    log = AuditLog.objects.get()
    assert (log.action, log.target_type, log.target_id) == (
        "assessment.review",
        "assessment",
        flagged.pk,
    )
    assert log.actor == agent and log.metadata["outcome"] == "cleared"


def test_review_confirm_requires_note(api, flagged):
    r = api.post(f"{BASE}/assessments/{flagged.pk}/review/", {"outcome": "confirmed"})
    assert r.status_code == 400 and "note" in r.json()
    assert AuditLog.objects.count() == 0


def test_review_twice_conflicts(api, flagged):
    url = f"{BASE}/assessments/{flagged.pk}/review/"
    assert api.post(url, {"outcome": "cleared"}).status_code == 200
    assert api.post(url, {"outcome": "confirmed", "note": "x"}).status_code == 409
    assert AuditLog.objects.count() == 1


def test_cannot_review_allowed_assessment(api, owner, sitter):
    b = Booking.objects.create(
        owner=owner,
        sitter=sitter,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        amount=Decimal("20.00"),
    )
    a = score_booking(b)
    assert a.decision == RiskAssessment.Decision.ALLOW
    assert api.post(f"{BASE}/assessments/{a.pk}/review/", {"outcome": "cleared"}).status_code == 400


# --- users ---


def test_user_list_search_and_summary(api, flagged, owner):
    data = api.get(f"{BASE}/users/?search=owner").json()
    assert data["count"] == 1
    assert data["results"][0]["max_score"] == 40 and data["results"][0]["assessment_count"] == 1


def test_user_detail_has_risk_history(api, flagged, owner):
    data = api.get(f"{BASE}/users/{owner.pk}/").json()
    assert data["recent_assessments"][0]["id"] == flagged.pk


def test_suspend_and_reinstate_with_audit(api, agent, sitter):
    assert api.post(f"{BASE}/users/{sitter.pk}/suspend/", {}).status_code == 400  # reason required
    r = api.post(f"{BASE}/users/{sitter.pk}/suspend/", {"reason": "shared phone ring"})
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    sitter.refresh_from_db()
    assert sitter.status == User.Status.SUSPENDED
    assert api.post(f"{BASE}/users/{sitter.pk}/suspend/", {"reason": "again"}).status_code == 409

    assert (
        api.post(f"{BASE}/users/{sitter.pk}/reinstate/", {"reason": "appeal ok"}).status_code == 200
    )
    actions = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
    assert actions == ["user.suspend", "user.reinstate"]
    assert AuditLog.objects.first().metadata["reason"] == "appeal ok"


def test_agents_cannot_be_suspended(api, agent):
    other = User.objects.create_user("agent2", "a2@x.com", "pw", role=User.Role.AGENT)
    r = api.post(f"{BASE}/users/{other.pk}/suspend/", {"reason": "x"})
    assert r.status_code == 403
    assert AuditLog.objects.count() == 0


def test_audit_log_endpoint_filters(api, sitter):
    api.post(f"{BASE}/users/{sitter.pk}/suspend/", {"reason": "r"})
    data = api.get(f"{BASE}/audit/?target_type=user&target_id={sitter.pk}").json()
    assert data["count"] == 1 and data["results"][0]["actor_label"] == "agent"
    assert api.get(f"{BASE}/audit/?action=nope").json()["count"] == 0


# --- SPA session auth ---


def test_login_me_logout_flow(agent, settings):
    agent.set_password("secret-pw")
    agent.save()
    client = APIClient(enforce_csrf_checks=True)
    token = client.get(f"{BASE}/auth/csrf/").json()["csrfToken"]
    headers = {"HTTP_X_CSRFTOKEN": token}

    assert client.get(f"{BASE}/auth/me/").status_code in (401, 403)
    bad = client.post(f"{BASE}/auth/login/", {"username": "agent", "password": "no"}, **headers)
    assert bad.status_code == 401
    ok = client.post(
        f"{BASE}/auth/login/", {"username": "agent", "password": "secret-pw"}, **headers
    )
    assert ok.status_code == 200 and ok.json()["username"] == "agent"
    assert client.get(f"{BASE}/auth/me/").json()["role"] == "agent"

    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert client.post(f"{BASE}/auth/logout/", **{"HTTP_X_CSRFTOKEN": token}).status_code == 204
    assert client.get(f"{BASE}/auth/me/").status_code in (401, 403)


def test_login_requires_csrf_token(agent):
    client = APIClient(enforce_csrf_checks=True)
    r = client.post(f"{BASE}/auth/login/", {"username": "agent", "password": "pw"})
    assert r.status_code == 403


def test_non_agent_cannot_log_in(owner):
    owner.set_password("secret-pw")
    owner.save()
    client = APIClient(enforce_csrf_checks=True)
    token = client.get(f"{BASE}/auth/csrf/").json()["csrfToken"]
    r = client.post(
        f"{BASE}/auth/login/",
        {"username": "owner", "password": "secret-pw"},
        HTTP_X_CSRFTOKEN=token,
    )
    assert r.status_code == 401


# --- login rate limiting ---


def _login(client, token, username, password):
    return client.post(
        f"{BASE}/auth/login/",
        {"username": username, "password": password},
        HTTP_X_CSRFTOKEN=token,
    )


def test_lockout_after_repeated_failures_even_with_correct_password(agent, settings):
    agent.set_password("secret-pw")
    agent.save()
    settings.LOGIN_MAX_FAILURES = 3
    client = APIClient(enforce_csrf_checks=True)
    token = client.get(f"{BASE}/auth/csrf/").json()["csrfToken"]

    assert [_login(client, token, "agent", "bad").status_code for _ in range(3)] == [401] * 3
    locked = _login(client, token, "agent", "secret-pw")  # correct, but locked
    assert locked.status_code == 429
    assert locked["Retry-After"] == str(settings.LOGIN_LOCKOUT_SECONDS)


def test_success_resets_failure_count(agent, settings):
    agent.set_password("secret-pw")
    agent.save()
    settings.LOGIN_MAX_FAILURES = 3
    client = APIClient(enforce_csrf_checks=True)
    token = client.get(f"{BASE}/auth/csrf/").json()["csrfToken"]

    for _ in range(2):
        assert _login(client, token, "agent", "bad").status_code == 401
    assert _login(client, token, "agent", "secret-pw").status_code == 200
    client = APIClient(enforce_csrf_checks=True)  # fresh session
    token = client.get(f"{BASE}/auth/csrf/").json()["csrfToken"]
    for _ in range(2):  # counter restarted, so 2 more failures don't lock
        assert _login(client, token, "agent", "bad").status_code == 401
    assert _login(client, token, "agent", "secret-pw").status_code == 200


def test_lockout_is_per_username_and_unknown_users_count_too(agent, settings):
    settings.LOGIN_MAX_FAILURES = 2
    client = APIClient(enforce_csrf_checks=True)
    token = client.get(f"{BASE}/auth/csrf/").json()["csrfToken"]
    for _ in range(2):
        assert _login(client, token, "ghost", "x").status_code == 401
    assert _login(client, token, "ghost", "x").status_code == 429  # no user enumeration
    assert _login(client, token, "agent", "x").status_code == 401  # other username unaffected


def test_ip_throttle_limits_username_spraying(db, settings):
    from rest_framework.settings import api_settings

    from apps.console.auth import LoginView

    settings.LOGIN_MAX_FAILURES = 1000  # isolate the per-IP throttle
    LoginView.throttle_classes[0].THROTTLE_RATES = {
        **api_settings.DEFAULT_THROTTLE_RATES,
        "login": "3/min",
    }
    try:
        client = APIClient(enforce_csrf_checks=True)
        token = client.get(f"{BASE}/auth/csrf/").json()["csrfToken"]
        codes = [_login(client, token, f"user{i}", "x").status_code for i in range(5)]
        assert codes == [401, 401, 401, 429, 429]
    finally:
        LoginView.throttle_classes[0].THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES


# --- sitter-side risk ---


def test_sitter_sees_risk_of_bookings_they_received(api, flagged, sitter):
    row = api.get(f"{BASE}/users/?search=sitter").json()["results"][0]
    assert row["username"] == "sitter"
    assert row["max_score"] is None  # nothing as an owner
    assert row["sitter_max_score"] == 40 and row["sitter_flagged_count"] == 1
    assert row["risk_score"] == 40  # worst of both roles

    detail = api.get(f"{BASE}/users/{sitter.pk}/").json()
    assert detail["recent_assessments"] == []
    assert [a["id"] for a in detail["received_assessments"]] == [flagged.pk]


def test_users_ordered_by_overall_risk(api, flagged, owner, sitter):
    clean = User.objects.create_user("clean", "c@x.com", "pw")
    names = [u["username"] for u in api.get(f"{BASE}/users/").json()["results"]]
    assert set(names[:2]) == {"owner", "sitter"}  # both carry the 40
    assert names.index("clean") > names.index("owner")
    assert clean.pk


# --- message moderation queue ---


@pytest.fixture
def flagged_message(owner, sitter, django_capture_on_commit_callbacks):
    from apps.moderation.models import Message

    booking = Booking.objects.create(
        owner=owner, sitter=sitter, start_date=date(2026, 12, 1), end_date=date(2026, 12, 2),
        amount=Decimal("50.00"),
    )  # fmt: skip
    with django_capture_on_commit_callbacks(execute=True):
        Message.objects.create(booking=booking, sender=sitter, body="Pay me on Bizum, skip the app")
        Message.objects.create(booking=booking, sender=owner, body="Thanks, see you at 9!")
    return booking


def test_moderation_queue_lists_flagged_with_reasons(api, flagged_message):
    data = api.get(f"{BASE}/messages/?verdict=flagged&review_status=pending").json()
    assert data["count"] == 1
    item = data["results"][0]
    assert item["message"]["sender"] == "sitter"
    assert item["categories"] == ["off_platform_payment"]
    assert item["reasons"][0].startswith("PAY_APP_OFF_PLATFORM")
    assert api.get(f"{BASE}/messages/").json()["count"] == 2  # clean one is listed unfiltered


def test_moderation_review_audited_and_not_repeatable(api, flagged_message):
    item = api.get(f"{BASE}/messages/?verdict=flagged").json()["results"][0]
    url = f"{BASE}/messages/{item['id']}/review/"
    assert api.post(url, {"outcome": "confirmed"}).status_code == 400  # note required
    r = api.post(url, {"outcome": "confirmed", "note": "off-platform ask"})
    assert r.status_code == 200 and r.json()["review_status"] == "confirmed"
    assert api.post(url, {"outcome": "cleared"}).status_code == 409
    log = AuditLog.objects.get()
    assert (log.action, log.target_type) == ("message.review", "message")
    assert log.metadata["verdict"] == "flagged"


def test_clean_messages_cannot_be_reviewed(api, flagged_message):
    clean = api.get(f"{BASE}/messages/?verdict=clean").json()["results"][0]
    r = api.post(f"{BASE}/messages/{clean['id']}/review/", {"outcome": "cleared"})
    assert r.status_code == 400


def test_moderation_queue_requires_agent(owner, flagged_message):
    client = APIClient()
    client.force_authenticate(owner)
    assert client.get(f"{BASE}/messages/").status_code == 403


def test_moderation_verdict_filter_accepts_comma_list(api, flagged_message):
    assert api.get(f"{BASE}/messages/?verdict=flagged,needs_review").json()["count"] == 1
    assert api.get(f"{BASE}/messages/?verdict=flagged,clean").json()["count"] == 2
