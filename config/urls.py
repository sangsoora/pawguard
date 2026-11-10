from django.contrib import admin
from django.urls import include, path

from apps.core.views import health, metrics

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("metrics/", metrics, name="metrics"),
    path("api/console/", include("apps.console.urls")),
    path("api/verification/", include("apps.verification.urls")),
    path("api-auth/", include("rest_framework.urls")),  # session login for the browsable API
]
