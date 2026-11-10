import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import metrics

from . import services
from .models import VerificationCase
from .provider import get_provider

logger = logging.getLogger(__name__)


def send_to_provider(case_id: int) -> str | None:
    """Send a submitted case to the provider and store its reference. Idempotent."""
    with transaction.atomic():
        case = VerificationCase.objects.select_for_update().get(pk=case_id)
        if case.state != VerificationCase.State.SUBMITTED or case.provider_ref:
            return case.provider_ref  # already sent, or no longer waiting on the provider
        case.provider_ref = get_provider().submit(case)  # ProviderError propagates (retry)
        case.save(update_fields=["provider_ref", "updated_at"])
        return case.provider_ref


@shared_task(
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=8,
)
def send_to_provider_task(case_id: int) -> str | None:
    return send_to_provider(case_id)


@shared_task
def purge_documents_task() -> int:
    purged = services.purge_expired_documents()
    logger.info("Purged personal data from %s verification cases", purged)
    return purged


def resend_unsent(min_age_seconds: int | None = None) -> dict:
    """Re-send submissions that never got a provider reference (provider was down, worker died).

    Only cases older than `min_age_seconds` are touched, so a submission that is still being
    sent normally is left alone. `send_to_provider` is idempotent and locks the row, so
    overlapping sweeps cannot double-submit. One failing case never blocks the others.
    """
    age = settings.VERIFICATION_RESEND_AFTER_SECONDS if min_age_seconds is None else min_age_seconds
    cutoff = timezone.now() - timedelta(seconds=age)
    ids = list(
        VerificationCase.objects.filter(
            state=VerificationCase.State.SUBMITTED,
            provider_ref__isnull=True,
            submitted_at__lt=cutoff,
        ).values_list("pk", flat=True)
    )
    result = {"found": len(ids), "sent": 0, "failed": 0}
    for case_id in ids:
        try:
            send_to_provider(case_id)
        except Exception:
            logger.exception("Re-send failed for verification case %s", case_id)
            result["failed"] += 1
            metrics.VERIFICATION_RESEND.labels("failed").inc()
        else:
            result["sent"] += 1
            metrics.VERIFICATION_RESEND.labels("sent").inc()
    if ids:
        logger.info("verification re-send sweep", extra=result)
    return result


@shared_task
def resend_unsent_task() -> dict:
    return resend_unsent()
