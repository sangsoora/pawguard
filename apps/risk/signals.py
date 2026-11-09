import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.bookings.models import Booking

logger = logging.getLogger(__name__)


def _score(booking_id: int) -> None:
    # Imported lazily so tests can patch apps.risk.engine.score_booking.
    from . import engine

    try:
        booking = Booking.objects.select_related("owner", "sitter").get(pk=booking_id)
        engine.score_booking(booking)
    except Exception:
        # A scoring failure must never lose or block the booking itself.
        logger.exception("Risk scoring failed for booking %s", booking_id)


@receiver(post_save, sender=Booking, dispatch_uid="risk_autoscore_booking")
def autoscore_new_booking(sender, instance, created, raw=False, **kwargs):
    """Score each new booking once it is committed.

    Synchronous for now; this is the seam where a Celery task will replace the direct call.
    Disable with RISK_AUTOSCORE = False.
    """
    if not created or raw or not getattr(settings, "RISK_AUTOSCORE", True):
        return
    transaction.on_commit(lambda: _score(instance.pk))
