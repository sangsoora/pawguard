from django.http import JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure


def health(request):
    return JsonResponse({"status": "ok"})


def csrf_failure(request, reason=""):
    """JSON CSRF failure for API calls (with the reason), Django's page for everything else."""
    if request.path.startswith("/api/"):
        return JsonResponse({"detail": f"CSRF verification failed: {reason}"}, status=403)
    return django_csrf_failure(request, reason=reason)
