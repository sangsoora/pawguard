import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.bookings.models import Booking

from .tasks import autoscore, score_booking_task

logger = logging.getLogger(__name__)


def _dispatch(booking_id: int) -> None:
    """Hand scoring to Celery, or run it inline when async is off or the broker is down."""
    if getattr(settings, "RISK_ASYNC_SCORING", False):
        try:
            score_booking_task.delay(booking_id)
            return
        except Exception:
            # Broker unreachable: score inline so the booking is never left unscored.
            logger.exception("Could not enqueue scoring for booking %s; scoring inline", booking_id)
    try:
        autoscore(booking_id)
    except Exception:
        # A scoring failure must never lose or block the booking itself.
        logger.exception("Risk scoring failed for booking %s", booking_id)


@receiver(post_save, sender=Booking, dispatch_uid="risk_autoscore_booking")
def autoscore_new_booking(sender, instance, created, raw=False, **kwargs):
    """Score each new booking once it is committed.

    RISK_ASYNC_SCORING=True enqueues a Celery task; otherwise it runs inline.
    Disable entirely with RISK_AUTOSCORE = False.
    """
    if not created or raw or not getattr(settings, "RISK_AUTOSCORE", True):
        return
    transaction.on_commit(lambda: _dispatch(instance.pk))
