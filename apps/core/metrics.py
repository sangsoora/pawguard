"""Prometheus metrics for PawGuard.

Event counters are incremented where things happen. Backlog gauges (queue size, age of the
oldest waiting item) are computed from the database at scrape time by `QueueCollector`, so
they are always accurate and need no bookkeeping.

"Flags per hour" is a query, not a metric: `increase(pawguard_flags_total[1h])`.

This registry is per process. Under a multi-worker server (gunicorn with several workers) set
PROMETHEUS_MULTIPROC_DIR and use prometheus_client's multiprocess mode, or scrape each worker.
"""

import logging
import time

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger(__name__)

registry = CollectorRegistry()

# -- Trust & Safety outcomes --
FLAGS = Counter(
    "pawguard_flags_total",
    "Items flagged for attention, by source (risk booking, message, verification).",
    ["source", "kind"],
    registry=registry,
)
RISK_ASSESSMENTS = Counter(
    "pawguard_risk_assessments_total", "Booking risk assessments.", ["decision"], registry=registry
)
RISK_SCORE = Histogram(
    "pawguard_risk_score",
    "Distribution of booking risk scores (0-100).",
    buckets=(0, 10, 20, 30, 40, 50, 60, 80, 100),
    registry=registry,
)
RULE_HITS = Counter(
    "pawguard_rule_hits_total", "Risk rule hits.", ["rule", "shadow"], registry=registry
)
MODERATION = Counter(
    "pawguard_moderation_total", "Moderated messages.", ["verdict", "stage"], registry=registry
)
VERIFICATION_TRANSITIONS = Counter(
    "pawguard_verification_transitions_total",
    "Verification state changes.",
    ["to_state", "source"],
    registry=registry,
)
WEBHOOK_EVENTS = Counter(
    "pawguard_webhook_events_total",
    "Provider webhook outcomes (applied, duplicate, ignored, unknown_case, bad_signature, "
    "bad_payload).",
    ["outcome"],
    registry=registry,
)
AGENT_ACTIONS = Counter(
    "pawguard_agent_actions_total", "Actions taken by agents in the console.", ["action"],
    registry=registry,
)  # fmt: skip
LOGIN_FAILURES = Counter(
    "pawguard_login_failures_total", "Console login failures.", ["reason"], registry=registry
)

# -- LLM stage cost and latency --
LLM_CALLS = Counter(
    "pawguard_llm_calls_total", "Moderation LLM calls.", ["outcome"], registry=registry
)
LLM_TOKENS = Counter(
    "pawguard_llm_tokens_total", "Moderation LLM tokens.", ["direction"], registry=registry
)
LLM_LATENCY = Histogram(
    "pawguard_llm_latency_seconds",
    "Moderation LLM call latency.",
    buckets=(0.25, 0.5, 1, 2, 4, 8, 16),
    registry=registry,
)

# -- HTTP --
HTTP_REQUESTS = Counter(
    "pawguard_http_requests_total", "HTTP requests.", ["method", "route", "status"],
    registry=registry,
)  # fmt: skip
HTTP_LATENCY = Histogram(
    "pawguard_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    registry=registry,
)


class QueueCollector:
    """Backlog gauges, read from the database on every scrape."""

    def collect(self):
        size = GaugeMetricFamily(
            "pawguard_review_queue_size", "Items waiting for a human.", labels=["queue"]
        )
        age = GaugeMetricFamily(
            "pawguard_review_queue_oldest_age_seconds",
            "Age of the longest-waiting item, 0 when the queue is empty.",
            labels=["queue"],
        )
        try:
            for name, (count, oldest) in _queue_stats().items():
                size.add_metric([name], count)
                age.add_metric([name], max(0.0, time.time() - oldest.timestamp()) if oldest else 0)
        except Exception:
            # A database hiccup must not break the whole scrape (other metrics still matter).
            logger.exception("Could not compute queue gauges")
        yield size
        yield age

    def describe(self):
        return []


def _queue_stats():
    """{queue name: (pending count, created_at of the oldest pending item)}"""
    from django.db.models import Count, Min

    from apps.moderation.models import ModerationResult
    from apps.risk.models import RiskAssessment
    from apps.verification.models import VerificationCase

    def stats(qs, since="created_at"):
        agg = qs.aggregate(n=Count("pk"), oldest=Min(since))
        return agg["n"], agg["oldest"]

    return {
        "risk": stats(
            RiskAssessment.objects.filter(review_status="pending").exclude(decision="allow")
        ),
        "messages": stats(
            ModerationResult.objects.filter(review_status="pending").exclude(verdict="clean")
        ),
        # updated_at ~ when the case entered manual review (nothing else touches it meanwhile)
        "verification": stats(
            VerificationCase.objects.filter(state="manual_review"), since="updated_at"
        ),
    }


registry.register(QueueCollector())
