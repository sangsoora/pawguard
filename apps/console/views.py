from django.db import transaction
from django.db.models import Count, Max, Q
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core import audit
from apps.core.models import AuditLog
from apps.core.permissions import IsTrustAgent
from apps.moderation.models import ModerationResult
from apps.risk.models import RiskAssessment

from . import serializers as s


class ConsoleViewSet(viewsets.GenericViewSet):
    permission_classes = [IsTrustAgent]


class AssessmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, ConsoleViewSet):
    """Review queue.

    Filters: ?decision=review|block|allow, ?review_status=pending|cleared|confirmed,
    ?min_score=40, ?user=<id>. Ordering: ?ordering=-score (default) | created_at | -created_at.
    """

    serializer_class = s.AssessmentSerializer
    ORDERINGS = {"score", "-score", "created_at", "-created_at"}

    def get_queryset(self):
        qs = RiskAssessment.objects.select_related(
            "user", "reviewed_by", "booking__owner", "booking__sitter"
        ).prefetch_related("hits")
        p = self.request.query_params
        if p.get("decision"):
            qs = qs.filter(decision=p["decision"])
        if p.get("review_status"):
            qs = qs.filter(review_status=p["review_status"])
        if p.get("min_score", "").isdigit():
            qs = qs.filter(score__gte=int(p["min_score"]))
        if p.get("user", "").isdigit():
            qs = qs.filter(user_id=int(p["user"]))
        ordering = p.get("ordering", "-score")
        if ordering not in self.ORDERINGS:
            ordering = "-score"
        return qs.order_by(ordering, "-id")

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        """Resolve an assessment as cleared (false positive) or confirmed (true positive)."""
        self.get_object()  # 404 for unknown ids
        return resolve_review(
            request,
            RiskAssessment,
            pk,
            reviewable=lambda a: a.decision != RiskAssessment.Decision.ALLOW,
            not_reviewable="Only review/block assessments can be reviewed.",
            audit_action="assessment.review",
            target_type="assessment",
            audit_extra=lambda a: {"score": a.score},
            respond=lambda: self.get_serializer(self.get_object()).data,
        )


def resolve_review(
    request,
    model,
    pk,
    *,
    reviewable,
    not_reviewable,
    audit_action,
    target_type,
    audit_extra,
    respond,
):
    """Shared "agent resolves a flagged item" flow: validate, lock, 409 on re-review, audit."""
    input_ = s.ReviewInputSerializer(data=request.data)
    input_.is_valid(raise_exception=True)
    with transaction.atomic():
        obj = model.objects.select_for_update().get(pk=pk)
        if not reviewable(obj):
            return Response({"detail": not_reviewable}, status=status.HTTP_400_BAD_REQUEST)
        if obj.review_status != "pending":
            return Response(
                {"detail": f"Already {obj.review_status}."}, status=status.HTTP_409_CONFLICT
            )
        obj.review_status = input_.validated_data["outcome"]
        obj.review_note = input_.validated_data["note"]
        obj.reviewed_by = request.user
        obj.reviewed_at = timezone.now()
        obj.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"])
        audit.record(
            request.user,
            audit_action,
            target_type,
            obj.pk,
            outcome=obj.review_status,
            note=obj.review_note,
            **audit_extra(obj),
        )
    return Response(respond())


class ModerationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, ConsoleViewSet):
    """Message moderation queue. Filters: ?verdict=flagged|needs_review|clean (comma-separated),
    ?review_status=pending|cleared|confirmed. Newest first."""

    serializer_class = s.ModerationSerializer

    def get_queryset(self):
        qs = ModerationResult.objects.select_related(
            "message__sender", "message__booking", "reviewed_by"
        )
        p = self.request.query_params
        if p.get("verdict"):
            qs = qs.filter(verdict__in=p["verdict"].split(","))  # comma-separated list
        if p.get("review_status"):
            qs = qs.filter(review_status=p["review_status"])
        return qs.order_by("-created_at", "-id")

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        self.get_object()
        return resolve_review(
            request,
            ModerationResult,
            pk,
            reviewable=lambda r: r.verdict != ModerationResult.Verdict.CLEAN,
            not_reviewable="Clean messages do not need review.",
            audit_action="message.review",
            target_type="message",
            audit_extra=lambda r: {"verdict": r.verdict, "message_id": r.message_id},
            respond=lambda: self.get_serializer(self.get_object()).data,
        )


class UserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, ConsoleViewSet):
    """Users with their risk summary. Search: ?search=<text>. Filter: ?status=, ?role=."""

    def get_serializer_class(self):
        return s.UserDetailSerializer if self.action == "retrieve" else s.UserSerializer

    def get_queryset(self):
        # Risk attaches to the booking *owner*; for sitters we also surface the assessments of
        # bookings they received, so a sitter linked to a fraud ring is visible on their profile.
        qs = User.objects.annotate(
            max_score=Max("risk_assessments__score"),
            assessment_count=Count("risk_assessments", distinct=True),
            sitter_max_score=Max("bookings_as_sitter__risk_assessments__score"),
            sitter_flagged_count=Count(
                "bookings_as_sitter__risk_assessments",
                filter=~Q(bookings_as_sitter__risk_assessments__decision="allow"),
                distinct=True,
            ),
        ).annotate(
            risk_score=Greatest(Coalesce("max_score", 0), Coalesce("sitter_max_score", 0)),
        )
        p = self.request.query_params
        if p.get("search"):
            term = p["search"]
            qs = qs.filter(
                Q(username__icontains=term)
                | Q(email__icontains=term)
                | Q(phone_number__icontains=term)
            )
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("role"):
            qs = qs.filter(role=p["role"])
        return qs.order_by("-risk_score", "id")

    def _change_status(self, request, pk, *, to, required_from, action_name):
        input_ = s.ReasonInputSerializer(data=request.data)
        input_.is_valid(raise_exception=True)
        with transaction.atomic():
            target = User.objects.select_for_update().get(pk=pk)
            if target.role == User.Role.AGENT:
                return Response(
                    {"detail": "Agent accounts cannot be changed from the console."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if target.status != required_from:
                return Response(
                    {"detail": f"User is {target.status}, expected {required_from}."},
                    status=status.HTTP_409_CONFLICT,
                )
            target.status = to
            target.save(update_fields=["status"])
            audit.record(
                request.user,
                action_name,
                "user",
                target.pk,
                reason=input_.validated_data["reason"],
                previous_status=required_from,
            )
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        self.get_object()  # 404 first
        return self._change_status(
            request,
            pk,
            to=User.Status.SUSPENDED,
            required_from=User.Status.ACTIVE,
            action_name="user.suspend",
        )

    @action(detail=True, methods=["post"])
    def reinstate(self, request, pk=None):
        self.get_object()
        return self._change_status(
            request,
            pk,
            to=User.Status.ACTIVE,
            required_from=User.Status.SUSPENDED,
            action_name="user.reinstate",
        )


class AuditLogViewSet(mixins.ListModelMixin, ConsoleViewSet):
    """Read-only audit trail. Filters: ?target_type=user&target_id=3, ?action=user.suspend."""

    serializer_class = s.AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.all()
        p = self.request.query_params
        for field in ("action", "target_type"):
            if p.get(field):
                qs = qs.filter(**{field: p[field]})
        if p.get("target_id", "").isdigit():
            qs = qs.filter(target_id=int(p["target_id"]))
        return qs
