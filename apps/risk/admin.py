from django.contrib import admin

from .models import RiskAssessment, Rule, RuleHit


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "evaluator", "points", "mode", "updated_at")
    list_editable = ("mode", "points")
    list_filter = ("mode",)


class RuleHitInline(admin.TabularInline):
    model = RuleHit
    extra = 0
    can_delete = False
    readonly_fields = ("rule", "reason_code", "detail", "points", "shadow")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "user", "score", "decision", "created_at")
    list_filter = ("decision",)
    ordering = ("-score", "-created_at")
    raw_id_fields = ("booking", "user")
    inlines = [RuleHitInline]
