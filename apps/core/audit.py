import logging

from . import metrics
from .models import AuditLog

logger = logging.getLogger(__name__)


def record(actor, action: str, target_type: str, target_id: int, **metadata) -> AuditLog:
    """Write an audit entry. Call inside the same transaction as the change it describes."""
    entry = AuditLog.objects.create(
        actor=actor,
        actor_label=actor.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
    metrics.AGENT_ACTIONS.labels(action).inc()
    logger.info(
        "agent action",
        extra={
            "actor": actor.username,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
        },
    )
    return entry
