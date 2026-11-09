from django.core.management.base import BaseCommand

from apps.bookings.models import Booking
from apps.risk.engine import score_booking


class Command(BaseCommand):
    help = "Score bookings with the current rules (creates a new assessment per booking)."

    def add_arguments(self, parser):
        parser.add_argument("--unscored-only", action="store_true")

    def handle(self, *args, unscored_only, **options):
        qs = Booking.objects.select_related("owner", "sitter").order_by("created_at")
        if unscored_only:
            qs = qs.filter(risk_assessments__isnull=True)
        for booking in qs:
            a = score_booking(booking)
            hits = ", ".join(f"{h.reason_code}{'*' if h.shadow else ''}" for h in a.hits.all())
            self.stdout.write(
                f"booking {booking.pk:>3} "
                f"{booking.owner.username:>8}->{booking.sitter.username:<14} "
                f"score={a.score:>3} {a.decision:<6} {hits}"
            )
        self.stdout.write("(* = shadow rule, not counted)")
