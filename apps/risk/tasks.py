import logging

from celery import shared_task

from apps.bookings.models import Booking

from .engine import score_booking

logger = logging.getLogger(__name__)


def autoscore(booking_id: int) -> int | None:
    """Score a booking once. Idempotent: a booking is auto-scored at most once.

    Returns the assessment id, or None if the booking is gone or was already scored.
    """
    try:
        booking = Booking.objects.select_related("owner", "sitter").get(pk=booking_id)
    except Booking.DoesNotExist:
        logger.warning("Booking %s no longer exists; skipping scoring", booking_id)
        return None
    if booking.risk_assessments.exists():
        return None  # duplicate delivery or retry after partial success
    return score_booking(booking).pk


@shared_task(
    acks_late=True,  # redeliver if the worker dies mid-task
    autoretry_for=(Exception,),
    retry_backoff=2,  # 2s, 4s, 8s ...
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def score_booking_task(booking_id: int) -> int | None:
    return autoscore(booking_id)
