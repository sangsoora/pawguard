import logging

from celery import shared_task

from .llm import get_classifier
from .models import Message
from .pipeline import moderate_message

logger = logging.getLogger(__name__)


def moderate(message_id: int) -> int | None:
    """Moderate a message once. Idempotent: an already-moderated message is skipped."""
    try:
        message = Message.objects.get(pk=message_id)
    except Message.DoesNotExist:
        return None
    if hasattr(message, "moderation"):
        return None
    return moderate_message(message, get_classifier()).pk


@shared_task(
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=2,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def moderate_message_task(message_id: int) -> int | None:
    return moderate(message_id)
