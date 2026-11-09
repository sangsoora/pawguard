from django.contrib import admin
from django.urls import include, path

from apps.core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/console/", include("apps.console.urls")),
    path("api-auth/", include("rest_framework.urls")),  # session login for the browsable API
]
