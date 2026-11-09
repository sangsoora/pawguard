"""Sliding-window event counters on Redis sorted sets.

One sorted set per (namespace, subject): member = event id, score = event timestamp.
Counting "events in the last N seconds as of time T" is a ZCOUNT on (T-N, T], so the same
structure answers live queries and as-of queries for replayed events.

Both functions fail open: if Redis is unconfigured or erroring they return None/False and
callers fall back to the database, so a Redis outage degrades accuracy-of-speed, not scoring.
"""

import logging
from datetime import datetime
from functools import lru_cache

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

# Keys are pruned past this age and expire when idle. Must exceed the longest rule window.
RETENTION_SECONDS = 24 * 3600


@lru_cache(maxsize=1)
def _client_for(url: str):
    return redis.Redis.from_url(url, socket_timeout=0.2, socket_connect_timeout=0.2)


def get_client():
    url = getattr(settings, "REDIS_URL", "")
    return _client_for(url) if url else None


def _key(namespace: str, subject_id: int) -> str:
    return f"pawguard:window:{namespace}:{subject_id}"


def record_event(namespace: str, subject_id: int, event_id: int, at: datetime) -> bool:
    """Add an event. Idempotent per event_id. Returns False if Redis was unavailable."""
    client = get_client()
    if client is None:
        return False
    ts = at.timestamp()
    key = _key(namespace, subject_id)
    try:
        pipe = client.pipeline()
        pipe.zadd(key, {str(event_id): ts})
        pipe.zremrangebyscore(key, "-inf", ts - RETENTION_SECONDS)
        pipe.expire(key, RETENTION_SECONDS)
        pipe.execute()
        return True
    except redis.RedisError:
        logger.warning("Redis unavailable while recording window event", exc_info=True)
        return False


def count_events(namespace: str, subject_id: int, at: datetime, window_seconds: int) -> int | None:
    """Events in (at - window, at]. None means Redis is unavailable: use the fallback."""
    client = get_client()
    if client is None:
        return None
    ts = at.timestamp()
    try:
        return int(client.zcount(_key(namespace, subject_id), f"({ts - window_seconds}", ts))
    except redis.RedisError:
        logger.warning("Redis unavailable while counting window events", exc_info=True)
        return None
