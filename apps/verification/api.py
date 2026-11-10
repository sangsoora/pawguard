import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import metrics
from apps.core.permissions import IsMarketplaceUser

from . import services, signing
from .models import VerificationCase
from .tasks import send_to_provider, send_to_provider_task

logger = logging.getLogger(__name__)


@csrf_exempt  # authenticated by HMAC signature, not by session
@require_POST
def provider_webhook(request):
    """Receive provider events. Signature -> contract -> idempotent apply."""
    body = request.body
    try:
        signing.verify(
            settings.VERIFICATION_WEBHOOK_SECRET,
            body,
            request.headers.get("X-Provider-Signature", ""),
        )
    except signing.InvalidSignature as exc:
        logger.warning("Rejected webhook: %s", exc)
        metrics.WEBHOOK_EVENTS.labels("bad_signature").inc()
        return JsonResponse({"detail": "Invalid signature."}, status=401)
    try:
        payload = services.parse_event(body)
    except services.InvalidPayload as exc:
        metrics.WEBHOOK_EVENTS.labels("bad_payload").inc()
        return JsonResponse({"detail": f"Payload violates the contract: {exc}"}, status=400)
    outcome = services.handle_provider_event(payload)
    return JsonResponse({"status": outcome})


class SubmitSerializer(serializers.Serializer):
    full_name = serializers.CharField(min_length=2, max_length=200)
    document_number = serializers.RegexField(r"^[A-Za-z0-9-]{4,40}$")
    document_country = serializers.RegexField(r"^[A-Za-z]{2}$")


def _dispatch_to_provider(case_id: int) -> None:
    if settings.VERIFICATION_ASYNC:
        try:
            send_to_provider_task.delay(case_id)
            return
        except Exception:
            logger.exception("Could not enqueue provider submission for case %s", case_id)
    try:
        send_to_provider(case_id)
    except Exception:
        # The user's submission is saved; the case stays 'submitted' without a reference and
        # can be re-sent. Never fail the user's request over a provider outage.
        logger.exception("Provider submission failed for case %s", case_id)


def _status_payload(user) -> dict:
    """What a user may know about their own verification. Never includes personal data."""
    case = user.verification_cases.first()
    state = case.state if case else "none"
    return {
        "state": state,
        # (Re)submitting is allowed when nothing is in flight: no case, a request, or a rejection.
        "can_submit": state in ("none", "requested", "rejected"),
        "rejection_reason": case.rejection_reason if case and state == "rejected" else "",
        "requested_by_agent": bool(case and case.requested_by_id and state == "requested"),
    }


class MyVerificationView(APIView):
    """The caller's own verification status. Never returns PII."""

    permission_classes = [IsMarketplaceUser]

    def get(self, request):
        return Response(_status_payload(request.user))

    def post(self, request):
        data = SubmitSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            case = services.submit_documents(request.user, **data.validated_data)
        except services.SubmissionNotAllowed as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        from django.db import transaction

        transaction.on_commit(lambda: _dispatch_to_provider(case.pk))
        return Response(_status_payload(request.user), status=status.HTTP_202_ACCEPTED)


__all__ = ["provider_webhook", "MyVerificationView", "VerificationCase"]
