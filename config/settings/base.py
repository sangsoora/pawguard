from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    # local
    "apps.core",
    "apps.accounts",
    "apps.bookings",
    "apps.risk",
    "apps.moderation",
    "apps.console",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTH_USER_MODEL = "accounts.User"

# Cookies ignore ports, so on localhost any other local project shares the default names
# ("csrftoken", "sessionid") and can shadow or overwrite them. Use app-specific names.
CSRF_COOKIE_NAME = "pawguard-csrftoken"
SESSION_COOKIE_NAME = "pawguard-sessionid"
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# SQLite by default; set DATABASE_URL=postgres://... to switch to Postgres.
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

# Redis backs the sliding-window counters. Leave empty to fall back to DB counts.
REDIS_URL = env("REDIS_URL", default="")

# Cache backs login throttling/lockout. Redis when configured (shared across processes),
# otherwise per-process memory, which is fine for local dev.
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
        if REDIS_URL
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_RATES": {"login": "20/min"},  # per client IP, on top of the lockout
}

# --- Celery (broker defaults to REDIS_URL) ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL or "memory://")
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TIME_LIMIT = 30
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # fair dispatch for short tasks
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Score new bookings through Celery instead of inline. Needs a broker and a running worker.
RISK_ASYNC_SCORING = env.bool("RISK_ASYNC_SCORING", default=False)

# Login lockout: this many failures for one username from one IP locks it for LOCKOUT seconds.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60

# --- Message moderation ---
# Stage 2 (LLM) is opt-in: it costs money. Needs ANTHROPIC_API_KEY in the environment.
MODERATION_LLM_ENABLED = env.bool("MODERATION_LLM_ENABLED", default=False)
MODERATION_MODEL = env("MODERATION_MODEL", default="claude-opus-5-5")
# USD per million tokens, used for the cost estimate in eval_moderation (claude-opus-5-5 rates).
MODERATION_PRICE_PER_MTOK = {"input": 4.0, "output": 20.0}
MODERATION_ASYNC = env.bool("MODERATION_ASYNC", default=False)
