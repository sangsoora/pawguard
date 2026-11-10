import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle and lockout counters live in the cache; keep tests independent."""
    cache.clear()
    yield
    cache.clear()
