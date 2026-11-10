from django.conf import settings
from django.db import models


class Message(models.Model):
    """A chat message between an owner and a sitter about a booking."""

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages"
    )
    body = models.TextField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["booking", "created_at"])]

    def __str__(self):
        return f"Message #{self.pk} by {self.sender_id}"


class ModerationResult(models.Model):
    class Verdict(models.TextChoices):
        CLEAN = "clean", "Clean"
        FLAGGED = "flagged", "Flagged"
        # Ambiguous and no automated way to settle it (LLM off, down, or refused): a human decides.
        NEEDS_REVIEW = "needs_review", "Needs review"

    class Stage(models.TextChoices):
        RULES = "rules", "Rules"
        LLM = "llm", "LLM"
        LLM_UNAVAILABLE = "llm_unavailable", "LLM unavailable"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CLEARED = "cleared", "Cleared (false positive)"
        CONFIRMED = "confirmed", "Confirmed (true positive)"

    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="moderation")
    verdict = models.CharField(max_length=14, choices=Verdict.choices)
    stage = models.CharField(max_length=16, choices=Stage.choices)
    categories = models.JSONField(default=list, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    confidence = models.FloatField(null=True, blank=True)

    # Cost / latency of the LLM stage (null when it wasn't used), for budgeting and the eval.
    llm_model = models.CharField(max_length=50, blank=True)
    llm_input_tokens = models.PositiveIntegerField(null=True, blank=True)
    llm_output_tokens = models.PositiveIntegerField(null=True, blank=True)
    llm_latency_ms = models.PositiveIntegerField(null=True, blank=True)

    review_status = models.CharField(
        max_length=10, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["review_status", "verdict", "-created_at"])]

    def __str__(self):
        return f"{self.verdict} ({self.stage}) message={self.message_id}"
