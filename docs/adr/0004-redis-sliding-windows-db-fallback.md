# 0004. Redis sliding windows for velocity, falling back to the database

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

A key fraud signal is velocity: too many bookings from one owner in a short window. The database
can answer "how many in the last hour" with a query, and does so correctly today. But velocity
counts sit on the hot path of every score, will multiply as more rules and signals (logins,
messages) are added, and some signals will have no database row at all. Counts must also be
answerable "as of" a past moment so replays are deterministic (ADR 0002).

## Decision

- One Redis sorted set per owner, key `pawguard:window:bookings:<owner_id>`: member = booking id
  (so recording is idempotent), score = event timestamp.
- "Events in the last N minutes as of T" is a single `ZCOUNT` over `(T - N, T]`.
- Old entries are pruned on each write and the key expires after 24 hours, which also caps the
  longest usable window.
- **Fail open to the database:** if `REDIS_URL` is unset or Redis errors, the rule falls back to an
  exact database count and logs a warning. Scoring never fails because Redis is down.
- Tests use `fakeredis`, and test settings blank `REDIS_URL` so the suite never touches a real Redis.

## Alternatives considered

- **Database only:** correct and simple. Kept as the fallback, but it puts a query on every
  score and does not help with row-less signals.
- **Fixed-window counters (`INCR` + `EXPIRE`):** cheapest, but a burst straddling a window
  boundary is undercounted, and as-of queries are impossible.
- **Token bucket or leaky bucket:** good for rate *limiting*, but we need counts we can explain
  ("4 bookings in 60 minutes"), not just a yes/no.
- **Redis streams or a time-series store:** more capability than needed.

## Consequences

**Good:**

- Cheap, accurate sliding windows, idempotent recording, and as-of queries.
- Resilient to Redis outages, with a measurable degraded mode.

**Costs and known gaps:**

- **Two sources of truth.** The database is authoritative; Redis only knows events recorded since
  it was connected. After a Redis flush or before it was introduced, a count can be too low, and a
  rule can silently miss. We chose availability over perfect accuracy.
- Two code paths to keep consistent.
- The 24-hour retention means rules cannot use longer windows without changing it.

## Revisit when

A rule needs a window longer than 24 hours, or we want Redis to be mandatory and drop the fallback
(then we must backfill it from the database on start).

## Code

- `apps/risk/windows.py`, `apps/risk/rules.py` (`booking_velocity`), `apps/risk/engine.py`
