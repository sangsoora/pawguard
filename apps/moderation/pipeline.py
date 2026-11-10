import logging
from dataclasses import dataclass, field

from .llm import Classifier, ClassifierError, LLMResult
from .models import Message, ModerationResult
from .rules import run_rules

logger = logging.getLogger(__name__)

V = ModerationResult.Verdict
S = ModerationResult.Stage


@dataclass
class Outcome:
    verdict: str
    stage: str
    categories: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    confidence: float | None = None
    llm: LLMResult | None = None  # set whenever the LLM stage ran successfully


def _uniq(items):
    return list(dict.fromkeys(items))


def classify_text(text: str, classifier: Classifier | None = None) -> Outcome:
    """Run the two-stage pipeline on raw text (no database access).

    1. Rules. A strong match flags immediately; no match is clean.
    2. Weak-only matches are ambiguous: ask the LLM if one is configured. If it is not, or it
       fails, the message goes to a human (needs_review) rather than being guessed.
    """
    matches = run_rules(text)
    strong = [m for m in matches if m.strength == "strong"]
    if strong:
        return Outcome(
            V.FLAGGED,
            S.RULES,
            _uniq(m.category for m in strong),
            [f"{m.code}: {m.reason}" for m in strong],
            confidence=1.0,
        )
    if not matches:
        return Outcome(V.CLEAN, S.RULES)

    weak_categories = _uniq(m.category for m in matches)
    weak_reasons = [f"{m.code}: {m.reason}" for m in matches]
    if classifier is None:
        return Outcome(V.NEEDS_REVIEW, S.LLM_UNAVAILABLE, weak_categories, weak_reasons)
    try:
        result = classifier.classify(text)
    except ClassifierError:
        logger.warning("LLM classification failed; routing to human review", exc_info=True)
        return Outcome(V.NEEDS_REVIEW, S.LLM_UNAVAILABLE, weak_categories, weak_reasons)

    if result.flagged:
        return Outcome(
            V.FLAGGED,
            S.LLM,
            _uniq([*result.categories, *weak_categories]),
            [*weak_reasons, f"LLM: {result.reason}"],
            result.confidence,
            result,
        )
    return Outcome(
        V.CLEAN,
        S.LLM,
        [],
        [*weak_reasons, f"LLM cleared: {result.reason}"],
        result.confidence,
        result,
    )


def moderate_message(message: Message, classifier: Classifier | None) -> ModerationResult:
    outcome = classify_text(message.body, classifier)
    llm = outcome.llm
    result, _ = ModerationResult.objects.update_or_create(
        message=message,
        defaults={
            "verdict": outcome.verdict,
            "stage": outcome.stage,
            "categories": outcome.categories,
            "reasons": outcome.reasons,
            "confidence": outcome.confidence,
            "llm_model": llm.model if llm else "",
            "llm_input_tokens": llm.input_tokens if llm else None,
            "llm_output_tokens": llm.output_tokens if llm else None,
            "llm_latency_ms": llm.latency_ms if llm else None,
        },
    )
    return result
