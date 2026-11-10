import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Message
from .tasks import moderate, moderate_message_task

logger = logging.getLogger(__name__)


def _dispatch(message_id: int) -> None:
    if settings.MODERATION_ASYNC:
        try:
            moderate_message_task.delay(message_id)
            return
        except Exception:
            logger.exception(
                "Could not enqueue moderation for message %s; running inline", message_id
            )
    try:
        moderate(message_id)
    except Exception:
        # Moderation failures must never lose or block the message itself.
        logger.exception("Moderation failed for message %s", message_id)


@receiver(post_save, sender=Message, dispatch_uid="moderation_new_message")
def moderate_new_message(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        transaction.on_commit(lambda: _dispatch(instance.pk))
