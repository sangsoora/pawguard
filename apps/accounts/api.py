"""End-user (owner / sitter) auth endpoints for the marketplace app."""

from django.urls import path

from apps.core.auth import BaseLoginView, BaseLogoutView, BaseMeView, CsrfView
from apps.core.permissions import IsMarketplaceUser


class LoginView(BaseLoginView):
    allowed_roles = ("owner", "sitter")
    scope = "account"


class LogoutView(BaseLogoutView):
    permission_classes = [IsMarketplaceUser]


class MeView(BaseMeView):
    permission_classes = [IsMarketplaceUser]


urlpatterns = [
    path("auth/csrf/", CsrfView.as_view()),
    path("auth/login/", LoginView.as_view()),
    path("auth/logout/", LogoutView.as_view()),
    path("auth/me/", MeView.as_view()),
]
