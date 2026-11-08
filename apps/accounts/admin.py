from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class PawGuardUserAdmin(UserAdmin):
    list_display = ("email", "username", "role", "status", "country", "date_joined")
    list_filter = ("role", "status", "country", "is_staff")
    search_fields = ("email", "username", "phone_number")
    fieldsets = (
        *UserAdmin.fieldsets,
        ("PawGuard", {"fields": ("role", "status", "phone_number", "country", "signup_ip")}),
    )
