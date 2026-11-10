# 0006. Measure AI output with a labelled dataset and a CI gate

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

A detector that "seems to work" is not evidence. Rules get edited, prompts get tuned and models
change, and any of those can silently make moderation worse. Treating AI output as trustworthy by
default is the failure mode to avoid: we want to check it critically and catch regressions
automatically.

## Decision

- A labelled dataset lives in the repo: `apps/moderation/eval/dataset.jsonl` (46 messages,
  including hard negatives such as a phone number shared for confirmed pickup logistics, and
  evasion cases such as zero-width and fullwidth characters).
- `apps/moderation/evaluation.py` scores the pipeline two ways, because the system is
  human-in-the-loop:
  - **Auto-flag** precision/recall: when it flags on its own, how often is it right, and how much
    does it catch without a human?
  - **Overall** precision/recall treating `flagged` or `needs_review` as "sent to a person".
  It also reports routing (rules vs LLM vs humans) and LLM tokens, estimated cost and latency.
- `python manage.py eval_moderation` prints the report; `--llm` runs the LLM stage with real API
  calls (costs money).
- **CI gate** (`test_eval_gate_rules_only`): on the rules-only pipeline, auto-flag precision >=
  0.95, auto-flag recall >= 0.75 and overall recall >= 0.95. A separate test uses a perfect
  "oracle" classifier to verify the harness arithmetic.

Current rules-only result: auto-flag precision 1.00, recall 0.81; overall recall 1.00 with
precision 0.78 (the 6 false positives are the cases the LLM stage is meant to clear).

## Alternatives considered

- **Manual spot checks:** do not scale and do not catch regressions.
- **LLM-as-judge:** adds a second unmeasured model to the loop.
- **Production-only metrics:** necessary eventually, but they arrive after users are affected.
- **A third-party eval framework:** more machinery than a 46-row dataset and one function.

## Consequences

**Good:**

- A rule or prompt change that hurts auto-flag precision, or lets suspicious messages bypass
  humans, fails CI.
- The two views make the real trade-off visible (precision of auto-actions vs load on humans).

**Costs and known gaps:**

- **The dataset is small and was written alongside the rules, so the numbers are optimistic.**
  Treat them as a regression floor, not as accuracy in the wild.
- The LLM stage is not in CI (cost and non-determinism); it is evaluated manually with `--llm`.
- No confidence intervals, and the thresholds were chosen by hand.

## Revisit when

There is enough reviewed production data. Agents' confirm/clear decisions are labelled examples;
fold them into the dataset, and consider a scheduled `--llm` evaluation.

## Code

- `apps/moderation/evaluation.py`, `apps/moderation/eval/dataset.jsonl`
- `apps/moderation/management/commands/eval_moderation.py`, `apps/moderation/tests.py`
