from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: audit entries cannot be added, edited or deleted from the admin."""

    list_display = ("created_at", "actor_label", "action", "target_type", "target_id")
    list_filter = ("action", "target_type")
    search_fields = ("actor_label",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
