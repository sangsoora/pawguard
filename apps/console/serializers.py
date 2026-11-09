from rest_framework import serializers

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.core.models import AuditLog
from apps.risk.models import RiskAssessment, RuleHit


class RuleHitSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleHit
        fields = ["reason_code", "detail", "points", "shadow"]


class BookingSummarySerializer(serializers.ModelSerializer):
    owner = serializers.CharField(source="owner.username")
    sitter = serializers.CharField(source="sitter.username")

    class Meta:
        model = Booking
        fields = ["id", "owner", "sitter", "start_date", "end_date", "amount", "currency", "status"]


class AssessmentSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="user.username")
    reviewed_by = serializers.CharField(source="reviewed_by.username", default=None)
    booking = BookingSummarySerializer()
    hits = RuleHitSerializer(many=True)

    class Meta:
        model = RiskAssessment
        fields = [
            "id",
            "user",
            "user_id",
            "booking",
            "score",
            "decision",
            "review_status",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
            "hits",
        ]


class ReviewInputSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["cleared", "confirmed"])
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["outcome"] == "confirmed" and not attrs["note"].strip():
            raise serializers.ValidationError(
                {"note": "A note is required when confirming a risk."}
            )
        return attrs


class UserSerializer(serializers.ModelSerializer):
    max_score = serializers.IntegerField(read_only=True, default=None)
    assessment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "role",
            "status",
            "country",
            "phone_number",
            "signup_ip",
            "date_joined",
            "max_score",
            "assessment_count",
        ]


class UserDetailSerializer(UserSerializer):
    recent_assessments = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [*UserSerializer.Meta.fields, "recent_assessments"]

    def get_recent_assessments(self, user):
        qs = (
            user.risk_assessments.select_related("booking__owner", "booking__sitter", "user")
            .prefetch_related("hits")
            .order_by("-created_at")[:20]
        )
        return AssessmentSerializer(qs, many=True).data


class ReasonInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor_label",
            "action",
            "target_type",
            "target_id",
            "metadata",
            "created_at",
        ]
