# PawGuard

Trust & Safety platform for a fictional pet-sitting marketplace (risk scoring, message moderation, review console).

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
