from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "sitter", "start_date", "end_date", "amount", "status")
    list_filter = ("status", "currency")
    search_fields = ("owner__email", "sitter__email")
    raw_id_fields = ("owner", "sitter")
