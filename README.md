# PawGuard

Trust & Safety platform for a fictional pet-sitting marketplace (risk scoring, message moderation, review console).

## Architecture decisions

The reasoning behind the main design choices (rules vs ML, inline vs async scoring, Redis windows,
the moderation pipeline, verification webhooks, PII handling, auth, observability) is recorded as
ADRs in [`docs/adr/`](docs/adr/README.md), including the known gaps we chose to live with. The
whole-system view (architecture, flows, threat model, failure modes, measured performance, what is
not built, open questions for reviewers) is in [`docs/design.md`](docs/design.md).

## Setup

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set DJANGO_SECRET_KEY
python manage.py migrate
python manage.py runserver
```

Health check: http://localhost:8000/health/

## Dev

```bash
pytest
ruff check . && ruff format --check .
```

## Async scoring (Celery + Redis)

New bookings are scored on creation. By default this runs inline; to score via Celery:

```bash
# .env
REDIS_URL=redis://localhost:6379/0
RISK_ASYNC_SCORING=True
```

```bash
celery -A config worker -l info
```

If the broker is unreachable when a booking is saved, scoring falls back to inline so no booking
goes unscored. The task is idempotent and retries with exponential backoff.

## Review console (React)

The agent console lives in `frontend/` (Vite + React + TypeScript) and talks to the Django API at
`/api/console/` using session auth with CSRF. Only users with role `agent` can sign in.

```bash
python manage.py runserver          # terminal 1: API on :8000
cd frontend && npm install && npm run dev   # terminal 2: console on http://localhost:5173
```

Sign in with a seeded agent (`agent1` / `pawguard-dev`, after `seed_users`). The Vite dev server
proxies `/api` to Django, and `CSRF_TRUSTED_ORIGINS` in `config/settings/local.py` trusts it.

```bash
cd frontend && npm run build && npx oxlint   # typecheck + production build + lint
```

## Login protection

Console login is limited two ways: 5 failed attempts for one username from one IP lock that
pair for 15 minutes (`LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_SECONDS`), and each IP is throttled to
20 login requests a minute. Counters live in the Django cache, which is Redis when `REDIS_URL` is
set (shared across processes) and per-process memory otherwise. Behind a reverse proxy, make sure
`REMOTE_ADDR` is the real client IP, or every user shares one counter.

## Message moderation

Chat messages are moderated on creation in two stages:

1. **Rules** (`apps/moderation/rules.py`): regexes over normalised text (Unicode-folded, invisible
   characters removed). A *strong* match flags immediately; no match is clean.
2. **LLM** (`apps/moderation/llm.py`): only for messages with *weak* signals (a phone number, a
   payment app name...). The LLM can clear or flag these but can never override a strong rule. It is
   off by default; if it is off or fails, the message goes to the human queue as `needs_review`.

```bash
# .env, to enable stage 2 (costs money; needs ANTHROPIC_API_KEY in the environment)
MODERATION_LLM_ENABLED=True
MODERATION_MODEL=claude-opus-5-5   # any Claude model id; pick a cheaper one for volume
```

```bash
python manage.py seed_messages     # moderated sample messages (after seed_users, seed_bookings)
python manage.py eval_moderation   # precision / recall on apps/moderation/eval/dataset.jsonl
python manage.py eval_moderation --llm   # same, with real LLM calls: adds cost and latency
```

`pytest` runs the same dataset as a regression gate (`test_eval_gate_rules_only`), so a rule
change that hurts auto-flag precision or lets suspicious messages bypass humans fails CI. The
dataset is small and was written alongside the rules, so treat its numbers as a floor for regression
detection, not as a measure of real-world accuracy: grow it with reviewed production messages.

## Identity verification

A KYC state machine (`apps/verification`): `requested -> submitted -> verified | rejected |
manual_review -> verified | rejected`. Transitions go through `services.transition()`, which locks
the row, refuses illegal moves and writes an append-only `VerificationEvent`.

- **Provider boundary:** `provider.py` has a `MockProvider`; swap `get_provider()` for a real vendor.
  Submissions go through a Celery task that retries with backoff and is idempotent.
- **Signed webhooks:** `POST /api/verification/webhook/` checks an HMAC-SHA256 signature
  (`X-Provider-Signature: t=<unix>,v1=<hex>`, 5-minute window against replay, fails closed if no
  secret is set), validates the body against `contracts/provider_webhook.schema.json`, and applies it
  idempotently by event id. Provider retries, duplicates and out-of-order events are acknowledged
  without changing state.
- **Contract tests:** the JSON Schema is the contract. Tests check that the provider's output
  validates against it, that PawGuard rejects anything off-contract, and that the examples in
  `contracts/examples/` conform.
- **PII:** name and document number are encrypted at rest (Fernet, key rotation supported via
  `FIELD_ENCRYPTION_KEYS`), never returned by the user API, and shown to agents only masked. A
  retention job blanks them after `VERIFICATION_RETENTION_DAYS` (default 30) once a case is
  decided; the case and its audit trail stay.

```bash
# .env (production must set its own values; in DEBUG a dev key is derived from SECRET_KEY)
FIELD_ENCRYPTION_KEYS=<key from Fernet.generate_key()>
VERIFICATION_WEBHOOK_SECRET=<long random string>
```

```bash
python manage.py simulate_provider_webhook <case_id> approved|rejected|review   # act as the provider
python manage.py purge_verification_documents                                   # retention (also daily via celery beat)
```

**User screen.** Owners and sitters sign in at <http://localhost:5173/account> (same React app,
separate login at `/api/account/auth/`; try `olivia` / `pawguard-dev` after `seed_users`) and submit
their details there. The page shows where the case stands, polls while a decision is pending, and
explains a rejection with the reason and lets the user try again. Roles are kept apart: an agent
cannot use this login, a user cannot use the console login, and suspended users are refused. Both
doors share the same CSRF, throttling and lockout (counted separately per door). Behind a real server,
make `/account` fall back to the app's `index.html` like any single-page route. There is no sign-up
yet; accounts come from `seed_users` or the admin.

**Stuck submissions.** If the provider is down when a user submits, the case is saved as
`submitted` without a provider reference. A sweeper (`resend_unsent_task`, every 5 minutes via
`celery -A config beat`, or `python manage.py resend_unsent_verifications`) re-sends cases older than
`VERIFICATION_RESEND_AFTER_SECONDS` (default 120). It is idempotent, one failing case never blocks
the others, and the `pawguard_verification_unsent_*` gauges plus a Grafana alert (stuck > 15 min)
show when something is persistently wrong.

## Observability

**Logs.** Structured JSON (`LOG_FORMAT=json`, the default outside DEBUG; plain text in DEBUG).
Every line carries the request id and, inside a span, `trace_id`/`span_id`, so a log line can be
joined to its trace. Extra fields are first-class keys:

```json
{"ts": "2026-11-10T01:12:12.902+00:00", "level": "INFO", "logger": "pawguard.request", "message": "request", "method": "GET", "path": "/health/", "route": "health/", "status": 200, "duration_ms": 111.7, "request_id": "demo-request-0001"}
```

`X-Request-ID` is accepted from callers (if it looks sane), generated otherwise, and echoed back.

**Metrics.** `GET /metrics/` (Prometheus). Set `METRICS_TOKEN` and send `Authorization: Bearer
<token>`; with no token it is open only in DEBUG. Key series:

| Metric | Use |
|---|---|
| `pawguard_flags_total{source,kind}` | **flags per hour**: `sum by (source) (increase(pawguard_flags_total[1h]))` |
| `pawguard_review_queue_size{queue}` | items waiting for a human (risk, messages, verification) |
| `pawguard_review_queue_oldest_age_seconds{queue}` | **review queue age**, computed from the DB at scrape time |
| `pawguard_rule_hits_total{rule,shadow}` | rule hit rates, shadow vs active |
| `pawguard_moderation_total{verdict,stage}`, `pawguard_llm_*` | moderation outcomes, LLM cost (tokens) and latency |
| `pawguard_webhook_events_total{outcome}` | provider webhooks: applied, duplicate, bad_signature... |
| `pawguard_http_*`, `pawguard_login_failures_total` | traffic, latency by route pattern, auth failures |

The registry is per process; with several server workers use Prometheus multiprocess mode.

**Traces.** OpenTelemetry for Django requests and Celery tasks, plus spans for
`risk.score_booking`, `moderation.moderate_message` and `moderation.llm_classify` (with model,
tokens and decision as attributes). Off by default:

```bash
OTEL_ENABLED=True
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

**Dashboard and alerts.** Committed under `observability/`: a Grafana dashboard
(`grafana/dashboards/pawguard.json`, 18 panels), provisioned alert rules
(`grafana/provisioning/alerting/rules.yml`: review queue older than 1h; webhook signature
failures) and a Prometheus scrape config. Bring it all up locally (Prometheus, Grafana, Jaeger):

```bash
docker compose -f docker-compose.observability.yml up
# Grafana http://localhost:3000 (admin/admin), Prometheus :9090, Jaeger UI :16686
```

A test checks that every metric the dashboard and alerts query actually exists, so a renamed
metric fails CI instead of silently blanking a panel.
