import logging

from django.conf import settings
from django.db import transaction
from opentelemetry import trace

from apps.bookings.models import Booking
from apps.core import metrics

from . import windows
from .models import RiskAssessment, Rule, RuleHit
from .rules import BOOKING_WINDOW, REGISTRY

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

# Score thresholds; override in settings.RISK_THRESHOLDS.
DEFAULT_THRESHOLDS = {"review": 40, "block": 80}


def decide(score: int) -> str:
    t = {**DEFAULT_THRESHOLDS, **getattr(settings, "RISK_THRESHOLDS", {})}
    if score >= t["block"]:
        return RiskAssessment.Decision.BLOCK
    if score >= t["review"]:
        return RiskAssessment.Decision.REVIEW
    return RiskAssessment.Decision.ALLOW


@transaction.atomic
def score_booking(booking: Booking) -> RiskAssessment:
    """Evaluate all non-off rules, persist an assessment with explainable hits.

    Active hits add to the score (capped at 100); shadow hits are recorded only.
    """
    with _tracer.start_as_current_span("risk.score_booking") as span:
        span.set_attribute("booking.id", booking.pk)
        assessment, hits = _score(booking)
        span.set_attribute("risk.score", assessment.score)
        span.set_attribute("risk.decision", assessment.decision)
        span.set_attribute("risk.rules_hit", [rule.code for rule, _ in hits])

    metrics.RISK_ASSESSMENTS.labels(assessment.decision).inc()
    metrics.RISK_SCORE.observe(assessment.score)
    for rule, _ in hits:
        metrics.RULE_HITS.labels(rule.code, str(rule.mode == Rule.Mode.SHADOW).lower()).inc()
    if assessment.decision != RiskAssessment.Decision.ALLOW:
        metrics.FLAGS.labels("risk", assessment.decision).inc()
    logger.info(
        "booking scored",
        extra={
            "booking_id": booking.pk,
            "score": assessment.score,
            "decision": assessment.decision,
            "rules": [rule.code for rule, _ in hits],
        },
    )
    return assessment


def _score(booking: Booking):
    windows.record_event(BOOKING_WINDOW, booking.owner_id, booking.pk, booking.created_at)

    hits = []
    for rule in Rule.objects.exclude(mode=Rule.Mode.OFF):
        fn = REGISTRY.get(rule.evaluator)
        if fn is None:
            logger.warning("Rule %s references unknown evaluator %r", rule.code, rule.evaluator)
            continue
        detail = fn(booking, rule.params)
        if detail:
            hits.append((rule, detail))

    score = min(100, sum(r.points for r, _ in hits if r.mode == Rule.Mode.ACTIVE))
    assessment = RiskAssessment.objects.create(
        booking=booking, user=booking.owner, score=score, decision=decide(score)
    )
    RuleHit.objects.bulk_create(
        RuleHit(
            assessment=assessment,
            rule=rule,
            reason_code=rule.code,
            detail=detail,
            points=rule.points,
            shadow=rule.mode == Rule.Mode.SHADOW,
        )
        for rule, detail in hits
    )
    return assessment, hits
