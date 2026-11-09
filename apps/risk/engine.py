import logging

from django.conf import settings
from django.db import transaction

from apps.bookings.models import Booking

from . import windows
from .models import RiskAssessment, Rule, RuleHit
from .rules import BOOKING_WINDOW, REGISTRY

logger = logging.getLogger(__name__)

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
    return assessment
