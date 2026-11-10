from .base import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
RISK_ASYNC_SCORING = False

# Tests must never touch a real Redis/broker, even if .env defines REDIS_URL.
# Redis-backed tests inject fakeredis explicitly.
REDIS_URL = ""
CELERY_BROKER_URL = "memory://"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
MODERATION_LLM_ENABLED = False
MODERATION_ASYNC = False

# Fixed test-only values (never used outside tests).
FIELD_ENCRYPTION_KEYS = ["Cn9wD0nUt3vq1u7f4pQe5mYb1o3xqk4m0Wv2bHq9r1A="]
VERIFICATION_WEBHOOK_SECRET = "test-webhook-secret"
VERIFICATION_ASYNC = False
