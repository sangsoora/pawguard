# 0003. Score inline by default; Celery is opt-in, with an inline fallback

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

Every new booking must be scored. Scoring is cheap today (a few queries and one Redis call), but
heavier checks are planned and scoring will eventually need to run off the request path. We also
want the project to run on a laptop without a broker, and a scoring problem must never lose or
break the booking itself.

## Decision

- A `post_save` signal on `Booking` (creation only, not fixtures) schedules scoring with
  `transaction.on_commit`, so scoring only ever sees committed data.
- `RISK_ASYNC_SCORING=False` (default): score inline. `True`: enqueue a Celery task
  (`score_booking_task`: `acks_late`, exponential backoff with jitter, 5 retries).
- The task is **idempotent**: it skips a booking that already has an assessment, so duplicate
  delivery and retries are safe.
- **If the broker is unreachable at enqueue time, score inline** instead of dropping the work.
- **Scoring failures are logged and swallowed**; the booking is already saved.
- The same pattern is used for message moderation and for sending verifications to the provider.

## Alternatives considered

- **Always synchronous in the request:** simplest, but ties booking latency to scoring and cannot
  grow into heavier checks.
- **Always asynchronous:** needs Redis and a worker even for local development and tests.
- **Score before saving, as a gate:** would let `block` actually stop a booking, but couples
  booking creation to the scorer's availability. Rejected for now; see ADR 0007.
- **Transactional outbox plus poller:** the most robust handoff; more machinery than needed yet.

## Consequences

**Good:**

- One code path serves both modes, so tests exercise the real logic.
- No booking is ever lost or blocked by scoring trouble.
- Moving to async is a setting change.

**Costs and known gaps:**

- In async mode a booking exists briefly unscored.
- **There is no sweeper for unscored bookings.** If scoring fails (inline) or the process dies
  between commit and dispatch (`on_commit` callbacks are in memory), the booking stays unscored
  until someone notices. Verification has a sweeper for the same problem; risk and moderation do
  not.
- Because scoring happens after commit, a high score can only *flag*, never prevent, a booking.

## Revisit when

We need pre-commit blocking of high-risk bookings, or we ever observe an unscored booking in
production. The fix then is an outbox table or a periodic "score anything unscored" sweep.

## Code

- `apps/risk/signals.py`, `apps/risk/tasks.py` (`autoscore`, `score_booking_task`)
- `config/settings/base.py` (`RISK_ASYNC_SCORING`, Celery settings)
