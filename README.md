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
