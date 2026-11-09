"""Rule evaluators.

Each evaluator takes (booking, params) and returns a human-readable detail string when
the rule fires, or None. Evaluate "as of" booking.created_at so backtesting gives the same
answer later as it would have live.
"""

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q

from apps.accounts.models import User
from apps.bookings.models import Booking

from . import windows

BOOKING_WINDOW = "bookings"
Evaluator = Callable[[Booking, dict], str | None]
REGISTRY: dict[str, Evaluator] = {}


def evaluator(name: str):
    def register(fn: Evaluator) -> Evaluator:
        REGISTRY[name] = fn
        return fn

    return register


@evaluator("new_account_high_value")
def new_account_high_value(booking, params):
    max_age = timedelta(days=params.get("max_account_age_days", 7))
    min_amount = Decimal(str(params.get("min_amount", 500)))
    age = max(booking.created_at - booking.owner.date_joined, timedelta(0))
    if age <= max_age and booking.amount >= min_amount:
        return f"account {age.days}d old, booking {booking.amount} {booking.currency}"
    return None


@evaluator("booking_velocity")
def booking_velocity(booking, params):
    window_minutes = params.get("window_minutes", 60)
    threshold = params.get("max_bookings", 3)
    # Redis sliding window first (the engine records the event before evaluating);
    # fall back to an exact DB count when Redis is unconfigured or down.
    count = windows.count_events(
        BOOKING_WINDOW, booking.owner_id, booking.created_at, window_minutes * 60
    )
    if count is None:
        count = Booking.objects.filter(
            owner=booking.owner,
            created_at__gt=booking.created_at - timedelta(minutes=window_minutes),
            created_at__lte=booking.created_at,
        ).count()
    if count > threshold:
        return f"{count} bookings in {window_minutes} min (max {threshold})"
    return None


@evaluator("shared_identifiers")
def shared_identifiers(booking, params):
    sitter = booking.sitter
    q = Q()
    if sitter.phone_number:
        q |= Q(phone_number=sitter.phone_number)
    if sitter.signup_ip:
        q |= Q(signup_ip=sitter.signup_ip)
    if not q:
        return None
    others = User.objects.filter(q).exclude(pk=sitter.pk)
    if others.count() >= params.get("min_linked_accounts", 1):
        names = ", ".join(others.values_list("username", flat=True)[:5])
        return f"sitter shares phone/IP with: {names}"
    return None


@evaluator("sitter_suspended")
def sitter_suspended(booking, params):
    if booking.sitter.status == User.Status.SUSPENDED:
        return f"sitter {booking.sitter.username} is suspended"
    return None
