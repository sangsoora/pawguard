from django.conf import settings
from django.db import models

from .fields import EncryptedTextField


class VerificationCase(models.Model):
    """One identity-verification attempt for a user (a KYC state machine).

    requested -> submitted -> verified | rejected | manual_review -> verified | rejected
    Transitions are enforced in services.transition(); never assign `state` directly.
    """

    class State(models.TextChoices):
        REQUESTED = "requested", "Requested"  # an agent asked; the user hasn't submitted yet
        SUBMITTED = "submitted", "Submitted"  # documents sent to the provider
        MANUAL_REVIEW = "manual_review", "Manual review"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_cases"
    )
    state = models.CharField(max_length=14, choices=State.choices, default=State.REQUESTED)
    provider_ref = models.CharField(max_length=100, unique=True, null=True, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    # PII: encrypted at rest, blanked by the retention job after the case is decided.
    full_name = EncryptedTextField(blank=True)
    document_number = EncryptedTextField(blank=True)
    document_country = models.CharField(max_length=2, blank=True)

    rejection_reason = models.CharField(max_length=500, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["state", "decided_at"]),
        ]

    def __str__(self):
        return f"Verification #{self.pk} user={self.user_id} {self.state}"


class VerificationEvent(models.Model):
    """Append-only audit trail of every state change, who caused it, and why."""

    class Source(models.TextChoices):
        USER = "user", "User"
        PROVIDER = "provider", "Provider webhook"
        AGENT = "agent", "Agent"
        SYSTEM = "system", "System"

    case = models.ForeignKey(VerificationCase, on_delete=models.CASCADE, related_name="events")
    from_state = models.CharField(max_length=14, blank=True)
    to_state = models.CharField(max_length=14)
    source = models.CharField(max_length=10, choices=Source.choices)
    actor_label = models.CharField(max_length=150, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"case {self.case_id}: {self.from_state or '-'} -> {self.to_state} ({self.source})"


class WebhookEvent(models.Model):
    """Every provider event id we have processed, for idempotency (providers retry)."""

    event_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=50)
    outcome = models.CharField(max_length=20, blank=True)  # applied | ignored | unknown_case
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_id} ({self.outcome or 'pending'})"
