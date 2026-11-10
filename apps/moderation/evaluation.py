"""Evaluation harness for the moderation pipeline.

Scores the pipeline against a labelled dataset (`eval/dataset.jsonl`) and reports the numbers
that matter for a human-in-the-loop system:

* auto-flag precision/recall - when the system flags a message on its own, how often is it
  right, and how many real violations does it catch without a human;
* overall precision/recall - treating "flagged OR needs_review" as the system saying "look at
  this", i.e. what actually reaches humans;
* routing - how much was settled by rules vs the LLM vs sent to humans, plus LLM cost/latency.

Run it with `python manage.py eval_moderation` (rules only) or `--llm` (real API calls).
"""

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from .llm import Classifier
from .models import ModerationResult
from .pipeline import classify_text

DATASET = Path(__file__).parent / "eval" / "dataset.jsonl"
V = ModerationResult.Verdict


@dataclass
class Case:
    text: str
    label: str  # "flag" | "clean"
    category: str = ""
    note: str = ""


@dataclass
class Metrics:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
        }  # fmt: skip


@dataclass
class EvalReport:
    total: int
    auto: Metrics  # positive = flagged
    overall: Metrics  # positive = flagged or needs_review
    routing: dict
    llm: dict
    errors: list = field(default_factory=list)  # (case, verdict) where the system was wrong

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "auto_flag": self.auto.as_dict(),
            "overall": self.overall.as_dict(),
            "routing": self.routing,
            "llm": self.llm,
            "errors": [
                {"text": c.text, "label": c.label, "verdict": v, "note": c.note}
                for c, v in self.errors
            ],
        }


def load_dataset(path: Path = DATASET) -> list[Case]:
    cases = []
    for line in path.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            cases.append(Case(d["text"], d["label"], d.get("category", ""), d.get("note", "")))
    return cases


def _record(m: Metrics, predicted: bool, actual: bool) -> None:
    if predicted and actual:
        m.tp += 1
    elif predicted:
        m.fp += 1
    elif actual:
        m.fn += 1
    else:
        m.tn += 1


def evaluate(cases: list[Case], classifier: Classifier | None = None) -> EvalReport:
    auto, overall = Metrics(), Metrics()
    routing = {"rules_clean": 0, "rules_flagged": 0, "llm_resolved": 0, "needs_review": 0}
    latencies, in_tok, out_tok, llm_calls = [], 0, 0, 0
    errors = []

    for case in cases:
        outcome = classify_text(case.text, classifier)
        actual = case.label == "flag"
        flagged = outcome.verdict == V.FLAGGED
        to_humans = outcome.verdict in (V.FLAGGED, V.NEEDS_REVIEW)
        _record(auto, flagged, actual)
        _record(overall, to_humans, actual)

        if outcome.verdict == V.NEEDS_REVIEW:
            routing["needs_review"] += 1
        elif outcome.llm is not None:
            routing["llm_resolved"] += 1
        elif flagged:
            routing["rules_flagged"] += 1
        else:
            routing["rules_clean"] += 1

        if outcome.llm is not None:
            llm_calls += 1
            in_tok += outcome.llm.input_tokens or 0
            out_tok += outcome.llm.output_tokens or 0
            if outcome.llm.latency_ms is not None:
                latencies.append(outcome.llm.latency_ms)
        if to_humans != actual or (flagged != actual and outcome.verdict != V.NEEDS_REVIEW):
            errors.append((case, outcome.verdict))

    price = settings.MODERATION_PRICE_PER_MTOK
    llm = {
        "calls": llm_calls,
        "share_of_messages": round(llm_calls / len(cases), 3) if cases else 0,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "est_cost_usd": round(in_tok / 1e6 * price["input"] + out_tok / 1e6 * price["output"], 4),
        "avg_latency_ms": round(statistics.mean(latencies)) if latencies else None,
        "p95_latency_ms": (
            round(statistics.quantiles(latencies, n=20)[-1]) if len(latencies) >= 2 else None
        ),
    }
    return EvalReport(len(cases), auto, overall, routing, llm, errors)
