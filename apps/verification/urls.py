from django.urls import path

from . import api

urlpatterns = [
    path("webhook/", api.provider_webhook),
    path("me/", api.MyVerificationView.as_view()),
]
