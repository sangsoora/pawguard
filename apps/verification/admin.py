from django.contrib import admin

from .models import VerificationCase, VerificationEvent, WebhookEvent


class EventInline(admin.TabularInline):
    model = VerificationEvent
    extra = 0
    can_delete = False
    readonly_fields = ("from_state", "to_state", "source", "actor_label", "detail", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(VerificationCase)
class VerificationCaseAdmin(admin.ModelAdmin):
    """PII fields are deliberately not shown in the admin."""

    list_display = ("id", "user", "state", "document_country", "decided_at", "purged_at")
    list_filter = ("state",)
    fields = ("user", "state", "provider_ref", "document_country", "rejection_reason",
              "submitted_at", "decided_at", "purged_at")  # fmt: skip
    readonly_fields = fields
    inlines = [EventInline]

    def has_add_permission(self, request):
        return False


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "outcome", "received_at")
