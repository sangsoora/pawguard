import logging

from celery import shared_task
from django.db import transaction

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
