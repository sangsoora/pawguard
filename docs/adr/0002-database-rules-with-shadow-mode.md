# 0002. Risk scoring with database-stored rules and shadow mode, not an ML model

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

Every booking needs a 0-100 risk score that agents can understand and defend. We have no labelled
fraud data yet, and the signals that matter will change as fraudsters adapt, so we need to tune
or add rules quickly and safely. A rule that looks right in a notebook can still flood the
review queue in production.

## Decision

- Rules are rows in the `Rule` table: `code`, `evaluator` (a function name), `params` (JSON),
  `points`, and `mode` = `off` | `shadow` | `active`.
- Evaluators are ordinary functions registered by name in `apps/risk/rules.py`. Each takes the
  booking and its params and returns a human-readable detail string if it fires.
- **Score** = sum of points of *active* hits, capped at 100. **Decision:** `allow` below 40,
  `review` from 40, `block` from 80 (`RISK_THRESHOLDS` overrides). See ADR 0007 for what `block`
  does and does not mean.
- **Shadow mode:** a shadow rule is evaluated and its hit is stored (`RuleHit.shadow = true`), but
  adds nothing to the score. We promote it to `active` once its hit rate looks right.
- Every hit carries a reason code and detail, shown to the agent.
- Evaluators measure "as of" the booking's `created_at`, so replaying an old booking gives the
  same answer it would have given live.
- The four starting rules are installed by a data migration (`0002_default_rules`).

## Alternatives considered

- **An ML classifier:** no labelled data to train on, opaque to agents, and harder to explain to
  a user who disputes a flag. Reviewed outcomes (cleared / confirmed) will become training data
  later; see "Revisit when".
- **Rules hard-coded in Python:** simple and code-reviewed, but every threshold change needs a
  deploy and there is no safe rollout path.
- **An external rules engine (OPA, Drools):** real power, but a heavy dependency for four rules.
- **An LLM scoring each booking:** slow, costly, non-deterministic, and unfit for a hot path.

## Consequences

**Good:**

- Scores are explainable by construction (reason codes), which is what agents and disputes need.
- Thresholds, points and modes can be changed in the admin without a deploy, with shadow mode as
  a safe on-ramp.
- Deterministic as-of evaluation makes replay and backtesting possible.

**Costs and known gaps:**

- A *new kind* of rule still needs code and a deploy. Only tuning is deploy-free.
- Additive points are crude: overlapping rules double-count, and there are no interaction terms
  or learned weights.
- **Rule changes made in the Django admin are not audited**, only `updated_at` changes. That is a
  gap for a Trust & Safety system, since a rule edit can change who gets flagged.
- **There is no real backtesting harness.** `score_bookings` re-scores existing bookings but
  creates new assessments rather than reporting what *would* have happened. The as-of design makes
  it buildable; it is not built.

## Revisit when

Enough reviewed outcomes accumulate (confirmed vs cleared) to calibrate points or train a model,
or when the number of rules makes manual tuning error-prone.

## Code

- `apps/risk/models.py` (`Rule`, `RuleHit`), `apps/risk/rules.py`, `apps/risk/engine.py`
- `apps/risk/migrations/0002_default_rules.py`
