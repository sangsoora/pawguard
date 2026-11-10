"""Session-based JSON login shared by the agent console and the end-user app.

Both get identical protection (CSRF, per-IP throttle, per-username lockout). Roles are kept
apart: a console login accepts only agents and an account login only owners/sitters, and the
failure message is the same for "wrong password" and "wrong kind of account".
"""

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import metrics


def user_payload(user):
    return {"id": user.pk, "username": user.username, "email": user.email, "role": user.role}


class CsrfView(APIView):
    """Sets the CSRF cookie; the SPA calls this once on load."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginInputSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


def _fail_key(scope: str, username: str, request) -> str:
    # Tracked per username *and* IP so one attacker can't lock a victim out from elsewhere
    # (the per-IP DRF throttle covers a single IP spraying many usernames). `scope` keeps the
    # console and the account app from sharing counters.
    ip = request.META.get("REMOTE_ADDR", "unknown")
    return f"login-fail:{scope}:{username.strip().lower()[:150]}:{ip}"


@method_decorator(csrf_protect, name="dispatch")
class BaseLoginView(APIView):
    """Subclasses set `allowed_roles` and `scope`."""

    allowed_roles: tuple[str, ...] = ()
    scope = "base"
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        data = LoginInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        key = _fail_key(self.scope, data.validated_data["username"], request)
        lockout = settings.LOGIN_LOCKOUT_SECONDS

        if cache.get(key, 0) >= settings.LOGIN_MAX_FAILURES:
            # Checked before authenticate(), so even the right password is refused while locked.
            response = Response(
                {"detail": f"Too many failed attempts. Try again in {lockout // 60} minutes."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = str(lockout)
            metrics.LOGIN_FAILURES.labels("locked_out").inc()
            return response

        user = authenticate(request, **data.validated_data)
        if user is None or user.role not in self.allowed_roles:
            metrics.LOGIN_FAILURES.labels("invalid_credentials").inc()
            cache.add(key, 0, timeout=lockout)
            try:
                cache.incr(key)
            except ValueError:  # key expired between add and incr
                cache.set(key, 1, timeout=lockout)
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        if getattr(user, "status", "active") == "suspended":
            # Only reachable with the right password, so this does not reveal who has an account.
            metrics.LOGIN_FAILURES.labels("suspended").inc()
            return Response(
                {"detail": "This account is suspended. Contact support."},
                status=status.HTTP_403_FORBIDDEN,
            )

        cache.delete(key)
        login(request, user)
        return Response(user_payload(user))


class BaseLogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BaseMeView(APIView):
    def get(self, request):
        return Response(user_payload(request.user))
