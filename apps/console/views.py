from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core import audit
from apps.core.models import AuditLog
from apps.core.permissions import IsTrustAgent
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
        input_ = s.ReviewInputSerializer(data=request.data)
        input_.is_valid(raise_exception=True)
        with transaction.atomic():
            self.get_object()  # 404 for unknown ids
            assessment = RiskAssessment.objects.select_for_update().get(pk=pk)
            if assessment.decision == RiskAssessment.Decision.ALLOW:
                return Response(
                    {"detail": "Only review/block assessments can be reviewed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if assessment.review_status != RiskAssessment.ReviewStatus.PENDING:
                return Response(
                    {"detail": f"Already {assessment.review_status}."},
                    status=status.HTTP_409_CONFLICT,
                )
            assessment.review_status = input_.validated_data["outcome"]
            assessment.review_note = input_.validated_data["note"]
            assessment.reviewed_by = request.user
            assessment.reviewed_at = timezone.now()
            assessment.save(
                update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at"]
            )
            audit.record(
                request.user,
                "assessment.review",
                "assessment",
                assessment.pk,
                outcome=assessment.review_status,
                note=assessment.review_note,
                score=assessment.score,
            )
        return Response(self.get_serializer(self.get_object()).data)


class UserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, ConsoleViewSet):
    """Users with their risk summary. Search: ?search=<text>. Filter: ?status=, ?role=."""

    def get_serializer_class(self):
        return s.UserDetailSerializer if self.action == "retrieve" else s.UserSerializer

    def get_queryset(self):
        qs = User.objects.annotate(
            max_score=Max("risk_assessments__score"),
            assessment_count=Count("risk_assessments", distinct=True),
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
        return qs.order_by("-max_score", "id")

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
