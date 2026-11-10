from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .metrics import registry


def health(request):
    return JsonResponse({"status": "ok"})


def csrf_failure(request, reason=""):
    """JSON CSRF failure for API calls (with the reason), Django's page for everything else."""
    if request.path.startswith("/api/"):
        return JsonResponse({"detail": f"CSRF verification failed: {reason}"}, status=403)
    return django_csrf_failure(request, reason=reason)


def metrics(request):
    """Prometheus scrape endpoint.

    Protected by `Authorization: Bearer <METRICS_TOKEN>` when a token is configured. With no
    token it is open only in DEBUG (local development) and closed otherwise.
    """
    import hmac

    token = settings.METRICS_TOKEN
    if token:
        provided = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(provided, token):
            return HttpResponseForbidden("Forbidden")
    elif not settings.DEBUG:
        return HttpResponseForbidden("Set METRICS_TOKEN to enable /metrics outside DEBUG.")
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
