"""Agent console auth. Shared behaviour lives in apps.core.auth."""

from apps.core.auth import BaseLoginView, BaseLogoutView, BaseMeView, CsrfView
from apps.core.permissions import IsTrustAgent

__all__ = ["CsrfView", "LoginView", "LogoutView", "MeView"]


class LoginView(BaseLoginView):
    allowed_roles = ("agent",)
    scope = "console"


class LogoutView(BaseLogoutView):
    permission_classes = [IsTrustAgent]


class MeView(BaseMeView):
    permission_classes = [IsTrustAgent]
