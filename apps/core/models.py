from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only record of every agent action taken through the console."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_label = models.CharField(max_length=150)  # survives actor deletion
    action = models.CharField(max_length=50)  # e.g. user.suspend, assessment.review
    target_type = models.CharField(max_length=50)
    target_id = models.PositiveBigIntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.actor_label} {self.action} {self.target_type}#{self.target_id}"
