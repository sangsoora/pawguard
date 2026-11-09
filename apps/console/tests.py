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
