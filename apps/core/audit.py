from .models import AuditLog


def record(actor, action: str, target_type: str, target_id: int, **metadata) -> AuditLog:
    """Write an audit entry. Call inside the same transaction as the change it describes."""
    return AuditLog.objects.create(
        actor=actor,
        actor_label=actor.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
