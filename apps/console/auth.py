"""JSON session auth for the React console (the SPA can't use DRF's HTML login form)."""

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

from apps.core.permissions import IsTrustAgent


def user_payload(user):
    return {"id": user.pk, "username": user.username, "email": user.email, "role": user.role}


class CsrfView(APIView):
    """Sets the csrftoken cookie; the SPA calls this once on load."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginInputSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


def _fail_key(username: str, request) -> str:
    # Tracked per username *and* IP so one attacker can't lock a victim out from elsewhere
    # (the per-IP DRF throttle covers a single IP spraying many usernames).
    ip = request.META.get("REMOTE_ADDR", "unknown")
    return f"login-fail:{username.strip().lower()[:150]}:{ip}"


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        data = LoginInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        key = _fail_key(data.validated_data["username"], request)
        lockout = settings.LOGIN_LOCKOUT_SECONDS

        if cache.get(key, 0) >= settings.LOGIN_MAX_FAILURES:
            # Checked before authenticate(), so even the right password is refused while locked.
            response = Response(
                {"detail": f"Too many failed attempts. Try again in {lockout // 60} minutes."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = str(lockout)
            return response

        user = authenticate(request, **data.validated_data)
        # Same message for bad credentials and non-agents: don't reveal which accounts exist.
        if user is None or user.role != "agent":
            cache.add(key, 0, timeout=lockout)
            try:
                cache.incr(key)
            except ValueError:  # key expired between add and incr
                cache.set(key, 1, timeout=lockout)
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        cache.delete(key)
        login(request, user)
        return Response(user_payload(user))


class LogoutView(APIView):
    permission_classes = [IsTrustAgent]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsTrustAgent]

    def get(self, request):
        return Response(user_payload(request.user))
