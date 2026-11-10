# Architecture Decision Records

An ADR records one significant technical decision: the situation, what we chose, what we
rejected, and what it costs us. Code shows *what* the system does; ADRs keep the *why* next to it.

Rules of the road:

- One decision per file, numbered, never renumbered.
- An accepted ADR is not rewritten. If we change our mind, write a new ADR that **supersedes**
  the old one and update the old one's status line. History stays readable.
- Be honest in *Consequences*. The negatives and known gaps are the most useful part.
- Link the code (`path/to/file.py`) so a reader can check the decision still holds.

Use [`0000-template.md`](0000-template.md) for new ones.

## Index

| # | Decision | Status |
|---|---|---|
| [0001](0001-modular-monolith.md) | One repo, a modular Django monolith plus a React app | Accepted |
| [0002](0002-database-rules-with-shadow-mode.md) | Risk scoring with database-stored rules and shadow mode, not an ML model | Accepted |
| [0003](0003-inline-scoring-celery-opt-in.md) | Score inline by default; Celery is opt-in, with an inline fallback | Accepted |
| [0004](0004-redis-sliding-windows-db-fallback.md) | Redis sliding windows for velocity, falling back to the database | Accepted |
| [0005](0005-two-stage-message-moderation.md) | Message moderation: rules first, LLM only for ambiguous cases | Accepted |
| [0006](0006-eval-harness-and-ci-gate.md) | Measure AI output with a labelled dataset and a CI gate | Accepted |
| [0007](0007-humans-decide-everything-audited.md) | The system recommends, humans decide, every action is audited | Accepted |
| [0008](0008-verification-provider-webhooks.md) | Identity verification: provider boundary, signed idempotent webhooks, schema contract | Accepted |
| [0009](0009-pii-encryption-and-retention.md) | Encrypt PII at rest, minimise who sees it, purge after retention | Accepted |
| [0010](0010-session-auth-csrf-lockout.md) | Session cookies, CSRF and lockout for the SPAs; two separate login doors | Accepted |
| [0011](0011-observability-as-code.md) | Observability: Prometheus, OpenTelemetry, JSON logs; dashboards and alerts as code | Accepted |

## Known gaps collected from the ADRs

Things we decided to live with *for now*. Each is explained in its ADR.

- Rule edits in the Django admin are not audited ([0002](0002-database-rules-with-shadow-mode.md)).
- A booking can stay unscored if scoring fails; there is no sweeper like verification has
  ([0003](0003-inline-scoring-celery-opt-in.md)).
- No true backtesting harness yet, only the as-of design that makes one possible
  ([0002](0002-database-rules-with-shadow-mode.md)).
- Abandoned verification submissions keep their PII indefinitely
  ([0009](0009-pii-encryption-and-retention.md)).
- No MFA for agents, and no global per-username login cap
  ([0010](0010-session-auth-csrf-lockout.md)).
- Tests run on SQLite while production is expected to use Postgres, so row-locking behaviour is
  untested ([0001](0001-modular-monolith.md)).
- Metrics are per process; Celery-worker events are invisible
  ([0011](0011-observability-as-code.md)).
