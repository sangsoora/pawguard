from rest_framework import serializers

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.core.models import AuditLog
from apps.moderation.models import Message, ModerationResult
from apps.risk.models import RiskAssessment, RuleHit
from apps.verification.models import VerificationCase, VerificationEvent


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
    # Risk from bookings this user received as a sitter, and the worst of both roles.
    sitter_max_score = serializers.IntegerField(read_only=True, default=None)
    sitter_flagged_count = serializers.IntegerField(read_only=True, default=0)
    risk_score = serializers.IntegerField(read_only=True, default=0)
    verification_state = serializers.CharField(read_only=True, default="none")

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
            "sitter_max_score",
            "sitter_flagged_count",
            "risk_score",
            "verification_state",
        ]


class UserDetailSerializer(UserSerializer):
    recent_assessments = serializers.SerializerMethodField()
    received_assessments = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [*UserSerializer.Meta.fields, "recent_assessments", "received_assessments"]

    @staticmethod
    def _serialize(qs):
        qs = qs.select_related("booking__owner", "booking__sitter", "user").prefetch_related("hits")
        return AssessmentSerializer(qs.order_by("-created_at")[:20], many=True).data

    def get_recent_assessments(self, user):
        """Assessments of bookings this user made as the owner."""
        return self._serialize(user.risk_assessments.all())

    def get_received_assessments(self, user):
        """Assessments of bookings where this user was the sitter."""
        return self._serialize(RiskAssessment.objects.filter(booking__sitter=user))


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


class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.CharField(source="sender.username")

    class Meta:
        model = Message
        fields = ["id", "booking_id", "sender", "body", "created_at"]


class ModerationSerializer(serializers.ModelSerializer):
    message = MessageSerializer()
    reviewed_by = serializers.CharField(source="reviewed_by.username", default=None)

    class Meta:
        model = ModerationResult
        fields = [
            "id",
            "message",
            "verdict",
            "stage",
            "categories",
            "reasons",
            "confidence",
            "llm_model",
            "llm_input_tokens",
            "llm_output_tokens",
            "llm_latency_ms",
            "review_status",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
        ]


class VerificationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationEvent
        fields = ["from_state", "to_state", "source", "actor_label", "detail", "created_at"]


class VerificationCaseSerializer(serializers.ModelSerializer):
    """Agents see the name and a masked document number, never the full document number."""

    user = serializers.CharField(source="user.username")
    user_id = serializers.IntegerField()
    document_number_masked = serializers.SerializerMethodField()
    events = VerificationEventSerializer(many=True, read_only=True)

    class Meta:
        model = VerificationCase
        fields = [
            "id",
            "user",
            "user_id",
            "state",
            "full_name",
            "document_number_masked",
            "document_country",
            "rejection_reason",
            "provider_ref",
            "submitted_at",
            "decided_at",
            "purged_at",
            "created_at",
            "events",
        ]

    def get_document_number_masked(self, case):
        number = case.document_number
        return "" if not number else "\u2022" * max(len(number) - 4, 0) + number[-4:]
