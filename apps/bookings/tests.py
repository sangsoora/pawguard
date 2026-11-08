from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.bookings.models import Booking


@pytest.fixture
def owner(db):
    return User.objects.create_user("owner", "owner@example.com", "pw", role=User.Role.OWNER)


@pytest.fixture
def sitter(db):
    return User.objects.create_user("sitter", "sitter@example.com", "pw", role=User.Role.SITTER)


def make(owner, sitter, **kw):
    defaults = {
        "owner": owner,
        "sitter": sitter,
        "start_date": date(2026, 12, 1),
        "end_date": date(2026, 12, 3),
        "amount": Decimal("90.00"),
    }
    return Booking.objects.create(**{**defaults, **kw})


def test_create_booking_defaults(owner, sitter):
    booking = make(owner, sitter)
    assert booking.status == Booking.Status.PENDING
    assert booking.currency == "EUR"
    assert owner.bookings_as_owner.count() == 1
    assert sitter.bookings_as_sitter.count() == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"end_date": date(2026, 11, 30)},
        {"amount": Decimal("0")},
    ],
)
def test_check_constraints(owner, sitter, overrides):
    with pytest.raises(IntegrityError), transaction.atomic():
        make(owner, sitter, **overrides)


def test_owner_cannot_book_self(owner):
    with pytest.raises(IntegrityError), transaction.atomic():
        make(owner, owner)


def test_user_email_unique(owner):
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("other", "owner@example.com", "pw")


def test_seed_bookings_idempotent_and_backdated(db, settings):
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.utils import timezone

    from apps.bookings.management.commands.seed_bookings import SEED_BOOKINGS

    settings.DEBUG = True
    with pytest.raises(CommandError):  # users not seeded yet
        call_command("seed_bookings")

    call_command("seed_users")
    call_command("seed_bookings")
    call_command("seed_bookings")
    assert Booking.objects.count() == len(SEED_BOOKINGS)

    burst = Booking.objects.filter(owner__username="lucas", status=Booking.Status.PENDING)
    assert burst.count() == 6
    assert all(timezone.now() - b.created_at < timezone.timedelta(hours=2) for b in burst)
