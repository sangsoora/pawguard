from django.conf import settings
from django.db import models


class Rule(models.Model):
    """A risk rule stored in the DB so it can be tuned or toggled without a deploy.

    `evaluator` names a function registered in apps.risk.rules; `params` is passed to it.
    """

    class Mode(models.TextChoices):
        OFF = "off", "Off"
        SHADOW = "shadow", "Shadow (record only, no effect on score)"
        ACTIVE = "active", "Active"

    code = models.CharField(max_length=50, unique=True, help_text="Reason code, e.g. NEW_ACCOUNT")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    evaluator = models.CharField(max_length=50)
    params = models.JSONField(default=dict, blank=True)
    points = models.PositiveSmallIntegerField(help_text="Added to the score when the rule hits")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.SHADOW)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.mode})"


class RiskAssessment(models.Model):
    class Decision(models.TextChoices):
        ALLOW = "allow", "Allow"
        REVIEW = "review", "Manual review"
        BLOCK = "block", "Block"

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, related_name="risk_assessments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_assessments"
    )
    score = models.PositiveSmallIntegerField()  # 0-100
    decision = models.CharField(max_length=10, choices=Decision.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"Assessment #{self.pk} booking={self.booking_id} score={self.score}"


class RuleHit(models.Model):
    """One rule firing within an assessment. Shadow hits are stored but score nothing."""

    assessment = models.ForeignKey(RiskAssessment, on_delete=models.CASCADE, related_name="hits")
    rule = models.ForeignKey(Rule, on_delete=models.PROTECT, related_name="hits")
    reason_code = models.CharField(max_length=50)
    detail = models.CharField(max_length=255)
    points = models.PositiveSmallIntegerField()
    shadow = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.reason_code}{' (shadow)' if self.shadow else ''}: {self.detail}"
