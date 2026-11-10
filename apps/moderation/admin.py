from django.contrib import admin

from .models import Message, ModerationResult


class ModerationInline(admin.StackedInline):
    model = ModerationResult
    extra = 0
    can_delete = False
    readonly_fields = ("verdict", "stage", "categories", "reasons", "confidence")
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "sender", "booking", "short_body", "created_at")
    raw_id_fields = ("booking", "sender")
    inlines = [ModerationInline]

    @admin.display(description="Body")
    def short_body(self, obj):
        return obj.body[:80]


@admin.register(ModerationResult)
class ModerationResultAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "verdict", "stage", "review_status", "created_at")
    list_filter = ("verdict", "stage", "review_status")
