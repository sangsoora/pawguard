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
