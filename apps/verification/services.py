import json
import logging
from datetime import timedelta
from pathlib import Path

import jsonschema
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import metrics

from .models import VerificationCase, VerificationEvent, WebhookEvent

logger = logging.getLogger(__name__)
S = VerificationCase.State
Source = VerificationEvent.Source

TRANSITIONS: dict[str, set[str]] = {
    S.REQUESTED: {S.SUBMITTED},
    S.SUBMITTED: {S.VERIFIED, S.REJECTED, S.MANUAL_REVIEW},
    S.MANUAL_REVIEW: {S.VERIFIED, S.REJECTED},
    S.VERIFIED: set(),
    S.REJECTED: set(),
}
OPEN_STATES = (S.REQUESTED, S.SUBMITTED, S.MANUAL_REVIEW)
DECIDED_STATES = (S.VERIFIED, S.REJECTED)


class InvalidTransition(Exception):
    pass


@transaction.atomic
def transition(
    case: VerificationCase, to: str, *, source: str, actor_label: str = "", detail: str = ""
) -> VerificationCase:
    """Move a case to `to` if the state machine allows it, recording an audit event.

    Locks the row so two concurrent webhooks/agents cannot both apply a transition.
    """
    case = VerificationCase.objects.select_for_update().get(pk=case.pk)
    if to not in TRANSITIONS[case.state]:
        raise InvalidTransition(f"{case.state} -> {to} is not allowed")
    previous, now = case.state, timezone.now()
    case.state = to
    if to == S.SUBMITTED:
        case.submitted_at = now
    if to in DECIDED_STATES:
        case.decided_at = now
    if to == S.REJECTED:
        case.rejection_reason = detail[:500]
    case.save()
    VerificationEvent.objects.create(
        case=case,
        from_state=previous,
        to_state=to,
        source=source,
        actor_label=actor_label,
        detail=detail[:500],
    )
    metrics.VERIFICATION_TRANSITIONS.labels(to, source).inc()
    if to == S.MANUAL_REVIEW:
        metrics.FLAGS.labels("verification", "manual_review").inc()
    logger.info(
        "verification transition",
        extra={"case_id": case.pk, "from_state": previous, "to_state": to, "source": source},
    )
    return case


# ---- provider webhook ----

_SCHEMA = json.loads(
    (Path(settings.BASE_DIR) / "contracts" / "provider_webhook.schema.json").read_text()
)
EVENT_TO_STATE = {
    "verification.approved": S.VERIFIED,
    "verification.rejected": S.REJECTED,
    "verification.needs_review": S.MANUAL_REVIEW,
}


class InvalidPayload(Exception):
    pass


def parse_event(body: bytes) -> dict:
    """Parse and validate a webhook body against the provider contract."""
    try:
        payload = json.loads(body)
        jsonschema.validate(payload, _SCHEMA)
    except (ValueError, jsonschema.ValidationError) as exc:
        raise InvalidPayload(str(exc).splitlines()[0]) from exc
    return payload


def handle_provider_event(payload: dict) -> str:
    outcome = _handle_provider_event(payload)
    metrics.WEBHOOK_EVENTS.labels(outcome).inc()
    return outcome


def _handle_provider_event(payload: dict) -> str:
    """Apply a validated provider event. Idempotent. Returns the outcome:
    applied | duplicate | ignored (illegal transition) | unknown_case.

    Always safe to acknowledge with 200: providers retry non-2xx, and none of these outcomes
    would succeed on retry.
    """
    try:
        with transaction.atomic():
            event, created = WebhookEvent.objects.get_or_create(
                event_id=payload["id"], defaults={"event_type": payload["type"]}
            )
            if not created:
                return "duplicate"
            case = VerificationCase.objects.filter(
                provider_ref=payload["data"]["reference"]
            ).first()
            if case is None:
                event.outcome = "unknown_case"
                event.save(update_fields=["outcome"])
                logger.warning("Webhook %s for unknown reference", payload["id"])
                return "unknown_case"
            try:
                transition(
                    case,
                    EVENT_TO_STATE[payload["type"]],
                    source=Source.PROVIDER,
                    actor_label="provider",
                    detail=payload["data"].get("reason", ""),
                )
                event.outcome = "applied"
            except InvalidTransition:
                event.outcome = "ignored"
                logger.warning("Webhook %s ignored: illegal transition", payload["id"])
            event.save(update_fields=["outcome"])
            return event.outcome
    except IntegrityError:  # two deliveries of the same event raced; the other one won
        return "duplicate"


# ---- retention ----


def purge_expired_documents(days: int | None = None, now=None) -> int:
    """Blank PII on decided cases older than `days` (default settings.VERIFICATION_RETENTION_DAYS).

    The case, its state and its audit trail are kept; only the personal data is removed.
    """
    days = settings.VERIFICATION_RETENTION_DAYS if days is None else days
    cutoff = (now or timezone.now()) - timedelta(days=days)
    purged = 0
    cases = VerificationCase.objects.filter(
        state__in=DECIDED_STATES, decided_at__lt=cutoff, purged_at__isnull=True
    )
    for case in cases:
        with transaction.atomic():
            case.full_name = ""
            case.document_number = ""
            case.purged_at = timezone.now()
            case.save(update_fields=["full_name", "document_number", "purged_at", "updated_at"])
            VerificationEvent.objects.create(
                case=case,
                from_state=case.state,
                to_state=case.state,
                source=Source.SYSTEM,
                actor_label="retention",
                detail=f"Personal data purged after {days} days",
            )
        purged += 1
    return purged


# ---- submission ----


class SubmissionNotAllowed(Exception):
    pass


@transaction.atomic
def submit_documents(user, *, full_name: str, document_number: str, document_country: str):
    """A user submits identity details. Reuses an agent's open request, else starts a new case."""
    cases = VerificationCase.objects.select_for_update().filter(user=user)
    if cases.filter(state=S.VERIFIED).exists():
        raise SubmissionNotAllowed("You are already verified.")
    if cases.filter(state__in=(S.SUBMITTED, S.MANUAL_REVIEW)).exists():
        raise SubmissionNotAllowed("A verification is already in progress.")
    case = cases.filter(state=S.REQUESTED).first() or VerificationCase.objects.create(user=user)
    case.full_name = full_name
    case.document_number = document_number
    case.document_country = document_country.upper()
    case.save()
    return transition(case, S.SUBMITTED, source=Source.USER, actor_label=user.username)


@transaction.atomic
def request_verification(user, *, agent) -> VerificationCase:
    """An agent asks a user to verify. At most one open or completed case per user."""
    existing = VerificationCase.objects.filter(
        user=user, state__in=(*OPEN_STATES, S.VERIFIED)
    ).first()
    if existing:
        raise SubmissionNotAllowed(f"User already has a {existing.state} verification.")
    case = VerificationCase.objects.create(user=user, requested_by=agent)
    VerificationEvent.objects.create(
        case=case,
        to_state=S.REQUESTED,
        source=Source.AGENT,
        actor_label=agent.username,
        detail="Verification requested by an agent",
    )
    return case
