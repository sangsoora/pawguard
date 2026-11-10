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
