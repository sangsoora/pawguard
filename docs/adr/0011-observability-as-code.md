# 0011. Observability: Prometheus, OpenTelemetry, JSON logs; dashboards and alerts as code

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

A Trust & Safety system fails quietly: a detector stops flagging, a queue grows unnoticed, a
webhook starts failing signature checks. The questions we need answered are "how many flags per
hour?", "how long has the oldest item been waiting?", "are verification results being applied?" and
"what did this request do?". Dashboards and alerts that live only in someone's Grafana UI are
unreviewed and easy to lose.

## Decision

- **Metrics: Prometheus, pull model**, at `/metrics/` (bearer token via `METRICS_TOKEN`; open
  only in DEBUG). Event counters are incremented where things happen (flags, rule hits, moderation
  outcomes, webhook outcomes, agent actions, login failures, LLM tokens and latency, HTTP).
- **Backlog gauges are computed from the database at scrape time** (queue size, oldest waiting
  item, stuck verification submissions), so they are always accurate and need no bookkeeping.
  "Flags per hour" is a query: `increase(pawguard_flags_total[1h])`.
- **HTTP metrics use the normalised route pattern** (`api/console/users/<pk>/`), never the raw
  path, so label cardinality stays bounded. User ids are never labels.
- **Logs:** structured JSON with a request id (accepted from `X-Request-ID` if sane, echoed back)
  and trace/span ids for correlation.
- **Traces:** OpenTelemetry for Django and Celery plus custom spans for scoring, moderation and the
  LLM call. Opt-in (`OTEL_ENABLED`), exported over OTLP.
- **Dashboard and alerts as code:** `observability/` holds the Grafana dashboard JSON,
  provisioned alert rules (queue older than 1 hour; webhook signature failures; stuck verification
  submissions) and a Prometheus config, with a Docker Compose stack for local use. **A test checks
  that every metric the dashboard and alerts reference actually exists**, so a rename fails CI
  instead of silently blanking a panel.

## Alternatives considered

- **Push metrics (StatsD, OTel metrics):** viable; pull gives free target health (`up`) and keeps
  the app simple.
- **Derive metrics from logs:** slower and lossy for the numbers we care about.
- **A hosted APM vendor:** powerful, but a cost and an account, and less instructive.
- **A dashboard inside the console:** would duplicate Grafana and mix operational and agent
  tooling.

## Consequences

**Good:**

- Backlog and "stuck" conditions are visible and alertable. Alerts are reviewed like code.
- Logs, metrics and traces can be joined by request id and trace id.

**Costs and known gaps:**

- **The registry is per process.** Counters only reflect events handled by the scraped process.
  Management commands do not appear (we noticed this when seeded data did not show on the
  dashboard), **and events handled inside Celery workers are invisible** unless workers expose
  their own metrics. Several web workers need Prometheus multiprocess mode.
- Scrape-time queries hit the database every scrape (cheap aggregates, but not free).
- Alert rules are validated for shape and metric names, not exercised against a live Grafana.
- No log shipping or retention is configured; logs go to stdout.

## Revisit when

Running multiple workers or Celery in production (multiprocess mode or a worker exporter), or when
the alert set grows (move to Prometheus alerting rules with `promtool` tests).

## Code

- `apps/core/metrics.py`, `apps/core/middleware.py`, `apps/core/jsonlog.py`, `apps/core/telemetry.py`
- `observability/`, `docker-compose.observability.yml`, `apps/core/test_observability.py`
