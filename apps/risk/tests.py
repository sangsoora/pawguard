from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.risk.engine import decide, score_booking
from apps.risk.models import Rule


@pytest.fixture
def owner(db):
    return User.objects.create_user("owner", "o@example.com", "pw", role=User.Role.OWNER)


@pytest.fixture
def sitter(db):
    return User.objects.create_user("sitter", "s@example.com", "pw", role=User.Role.SITTER)


def book(owner, sitter, amount="50.00", hours_ago=0):
    b = Booking.objects.create(
        owner=owner,
        sitter=sitter,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        amount=Decimal(amount),
    )
    Booking.objects.filter(pk=b.pk).update(created_at=timezone.now() - timedelta(hours=hours_ago))
    b.refresh_from_db()
    return b


def test_default_rules_are_seeded_by_migration(db):
    assert Rule.objects.filter(code="BOOKING_VELOCITY", mode="active").exists()
    assert Rule.objects.get(code="SHARED_IDENTIFIERS").mode == Rule.Mode.SHADOW


def test_clean_booking_scores_zero(owner, sitter):
    a = score_booking(book(owner, sitter))
    assert (a.score, a.decision) == (0, "allow")
    assert a.hits.count() == 0


def test_new_account_high_value_gives_reason_code(owner, sitter):
    a = score_booking(book(owner, sitter, amount="900.00"))
    assert a.score == 40
    assert a.decision == "review"
    hit = a.hits.get()
    assert hit.reason_code == "NEW_ACCOUNT_HIGH_VALUE"
    assert "900.00" in hit.detail


def test_velocity_fires_on_fourth_booking_in_window(owner, sitter):
    bookings = [book(owner, sitter, hours_ago=0.5) for _ in range(4)]
    scores = [score_booking(b).score for b in bookings]
    assert scores == [0, 0, 0, 40]
    last = score_booking(bookings[-1])
    assert last.hits.get().reason_code == "BOOKING_VELOCITY"


def test_shadow_rule_records_hit_but_not_score(owner, sitter):
    other = User.objects.create_user("twin", "t@example.com", "pw", phone_number="+1")
    sitter.phone_number = "+1"
    sitter.save()
    a = score_booking(book(owner, sitter))
    hit = a.hits.get(reason_code="SHARED_IDENTIFIERS")
    assert hit.shadow and other.username in hit.detail
    assert a.score == 0

    Rule.objects.filter(code="SHARED_IDENTIFIERS").update(mode=Rule.Mode.ACTIVE)
    assert score_booking(book(owner, sitter)).score == 30


def test_off_rules_are_skipped(owner, sitter):
    Rule.objects.update(mode=Rule.Mode.OFF)
    a = score_booking(book(owner, sitter, amount="9000.00"))
    assert a.score == 0 and a.hits.count() == 0


def test_score_is_capped_at_100(owner, sitter):
    sitter.status = User.Status.SUSPENDED
    sitter.save()
    Rule.objects.filter(code="NEW_ACCOUNT_HIGH_VALUE").update(points=90)
    assert score_booking(book(owner, sitter, amount="900.00")).score == 100


@pytest.mark.parametrize(
    "score,expected", [(0, "allow"), (39, "allow"), (40, "review"), (80, "block")]
)
def test_decide_thresholds(score, expected):
    assert decide(score) == expected


def test_new_booking_is_autoscored_after_commit(owner, sitter, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        b = Booking.objects.create(
            owner=owner,
            sitter=sitter,
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 2),
            amount=Decimal("900.00"),
        )
    a = b.risk_assessments.get()
    assert a.score == 40 and a.decision == "review"

    with django_capture_on_commit_callbacks(execute=True):
        b.save()  # updates do not re-score
    assert b.risk_assessments.count() == 1


def test_autoscore_can_be_disabled(owner, sitter, settings, django_capture_on_commit_callbacks):
    settings.RISK_AUTOSCORE = False
    with django_capture_on_commit_callbacks(execute=True):
        b = book(owner, sitter)
    assert b.risk_assessments.count() == 0


def test_scoring_failure_does_not_break_booking(
    owner, sitter, monkeypatch, django_capture_on_commit_callbacks
):
    def boom(booking):
        raise RuntimeError("scorer down")

    monkeypatch.setattr("apps.risk.tasks.score_booking", boom)
    with django_capture_on_commit_callbacks(execute=True):
        b = book(owner, sitter)
    assert Booking.objects.filter(pk=b.pk).exists()
    assert b.risk_assessments.count() == 0


# --- Redis sliding windows (fakeredis) ---


@pytest.fixture
def fake_redis(monkeypatch, settings):
    import fakeredis

    from apps.risk import windows

    client = fakeredis.FakeRedis()
    settings.REDIS_URL = "redis://fake"
    monkeypatch.setattr(windows, "get_client", lambda: client)
    return client


def test_window_counts_only_events_inside_window(fake_redis):
    from apps.risk import windows

    now = timezone.now()
    for i, minutes_ago in enumerate([90, 59, 30, 0]):
        windows.record_event("bookings", 1, i, now - timedelta(minutes=minutes_ago))
    assert windows.count_events("bookings", 1, now, 3600) == 3  # 90m ago excluded
    assert windows.count_events("bookings", 2, now, 3600) == 0  # other subject
    # as-of query in the past
    assert windows.count_events("bookings", 1, now - timedelta(minutes=45), 3600) == 2


def test_record_is_idempotent_and_prunes_old_events(fake_redis):
    from apps.risk import windows

    key = "pawguard:window:bookings:1"
    now = timezone.now()
    windows.record_event("bookings", 1, 8, now - timedelta(days=3))  # beyond retention
    windows.record_event("bookings", 1, 7, now)
    windows.record_event("bookings", 1, 7, now)  # same event id: no duplicate
    assert fake_redis.zcard(key) == 1  # the 3-day-old event was pruned
    assert windows.count_events("bookings", 1, now, 60) == 1
    assert fake_redis.ttl(key) > 0


def test_velocity_rule_uses_redis_window(owner, sitter, fake_redis):
    bookings = [book(owner, sitter, hours_ago=0.5) for _ in range(4)]
    assert [score_booking(b).score for b in bookings] == [0, 0, 0, 40]
    assert fake_redis.zcard(f"pawguard:window:bookings:{owner.pk}") == 4


def test_velocity_falls_back_to_db_when_redis_down(owner, sitter, monkeypatch, settings):
    import redis

    from apps.risk import windows

    class Down:
        def pipeline(self):
            raise redis.ConnectionError("down")

        def zcount(self, *a, **k):
            raise redis.ConnectionError("down")

    settings.REDIS_URL = "redis://down"
    monkeypatch.setattr(windows, "get_client", lambda: Down())
    bookings = [book(owner, sitter, hours_ago=0.5) for _ in range(4)]
    assert [score_booking(b).score for b in bookings] == [0, 0, 0, 40]


# --- Celery async scoring ---


def test_task_is_idempotent(owner, sitter):
    from apps.risk.tasks import score_booking_task

    b = book(owner, sitter)
    first = score_booking_task.delay(b.pk).get()  # eager in test settings
    assert first is not None
    assert score_booking_task.delay(b.pk).get() is None  # duplicate delivery is a no-op
    assert b.risk_assessments.count() == 1


def test_task_skips_deleted_booking(db):
    from apps.risk.tasks import score_booking_task

    assert score_booking_task.delay(999999).get() is None


def test_signal_enqueues_task_when_async(
    owner, sitter, settings, monkeypatch, django_capture_on_commit_callbacks
):
    settings.RISK_ASYNC_SCORING = True
    queued = []
    monkeypatch.setattr("apps.risk.signals.score_booking_task.delay", queued.append)
    with django_capture_on_commit_callbacks(execute=True):
        b = book(owner, sitter)
    assert queued == [b.pk]
    assert b.risk_assessments.count() == 0  # scoring is left to the worker


def test_signal_scores_inline_if_broker_down(
    owner, sitter, settings, monkeypatch, django_capture_on_commit_callbacks
):
    settings.RISK_ASYNC_SCORING = True

    def broker_down(booking_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr("apps.risk.signals.score_booking_task.delay", broker_down)
    with django_capture_on_commit_callbacks(execute=True):
        b = book(owner, sitter)
    assert b.risk_assessments.count() == 1
