import logging
import re
import time
import uuid

from .context import request_id
from .metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = logging.getLogger("pawguard.request")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_NAMED_GROUP = re.compile(r"\(\?P<(\w+)>[^)]*\)")


def route_label(match) -> str:
    """A readable, bounded-cardinality route such as `api/console/users/<pk>/`.

    DRF routers produce regex routes (`^users/(?P<pk>[^/.]+)/$`); tidy those up.
    """
    if match is None or not match.route:
        return "unmatched"
    route = _NAMED_GROUP.sub(r"<\1>", match.route)
    return route.replace("^", "").replace("$", "").replace("\\.", ".") or "/"


class ObservabilityMiddleware:
    """Request id, structured access log, and HTTP metrics.

    Accepts an inbound X-Request-ID (if it looks sane) so a request can be followed across
    services, otherwise generates one, and echoes it back in the response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        inbound = request.headers.get("X-Request-ID", "")
        rid = inbound if _VALID_ID.match(inbound) else uuid.uuid4().hex
        token = request_id.set(rid)
        started = time.perf_counter()
        status = 500
        try:
            response = self.get_response(request)
            status = response.status_code
            response["X-Request-ID"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - started
            # The URL *pattern* (not the raw path) keeps label cardinality bounded.
            route = route_label(getattr(request, "resolver_match", None))
            if route != "metrics/":
                HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
                HTTP_LATENCY.labels(request.method, route).observe(elapsed)
            user = getattr(request, "user", None)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.path,
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 1),
                    "user": user.username if user is not None and user.is_authenticated else None,
                },
            )
            request_id.reset(token)
