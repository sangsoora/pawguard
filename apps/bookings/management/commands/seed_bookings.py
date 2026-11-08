from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking

S = Booking.Status

# (owner, sitter, start in N days (negative = past), nights, amount, status, created N hours ago)
SEED_BOOKINGS = [
    # --- Normal traffic ---
    ("olivia", "emma", -20, 3, "120.00", S.COMPLETED, 24 * 25),
    ("olivia", "emma", -6, 2, "80.00", S.COMPLETED, 24 * 10),
    ("olivia", "emma", 14, 4, "160.00", S.CONFIRMED, 24 * 3),
    ("marc", "pablo", -12, 5, "225.00", S.COMPLETED, 24 * 18),
    ("marc", "pablo", 7, 2, "90.00", S.CONFIRMED, 24 * 2),
    ("sofia", "chloe", -30, 7, "385.00", S.COMPLETED, 24 * 40),
    ("sofia", "chloe", 21, 3, "150.00", S.PENDING, 5),
    ("lucas", "hans", -9, 1, "35.00", S.COMPLETED, 24 * 14),
    ("marc", "emma", -3, 2, "75.00", S.CANCELLED, 24 * 7),
    # --- High-value booking to a sitter sharing phone/IP with another account ---
    ("sofia", "quickcash1", 3, 14, "2400.00", S.PENDING, 2),
    # --- Burst: one owner books six different sitters within an hour ---
    ("lucas", "emma", 10, 2, "70.00", S.PENDING, 1),
    ("lucas", "pablo", 10, 2, "70.00", S.PENDING, 1),
    ("lucas", "chloe", 10, 2, "70.00", S.PENDING, 1),
    ("lucas", "hans", 10, 2, "70.00", S.PENDING, 1),
    ("lucas", "quickcash1", 10, 2, "70.00", S.PENDING, 1),
    ("lucas", "quickcash2", 10, 2, "70.00", S.PENDING, 1),
    # --- Sitter that is suspended ---
    ("olivia", "suspended_sam", -40, 3, "110.00", S.COMPLETED, 24 * 50),
]


class Command(BaseCommand):
    help = (
        "Create sample bookings for local development (run seed_users first). "
        "Idempotent: a booking is identified by owner + sitter + amount."
    )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_bookings only runs with DEBUG=True.")

        usernames = {name for row in SEED_BOOKINGS for name in row[:2]}
        users = {u.username: u for u in User.objects.filter(username__in=usernames)}
        missing = usernames - users.keys()
        if missing:
            raise CommandError(f"Missing users {sorted(missing)}. Run `seed_users` first.")

        today = timezone.localdate()
        now = timezone.now()
        created = 0
        for owner, sitter, start_in, nights, amount, status, hours_ago in SEED_BOOKINGS:
            start = today + timedelta(days=start_in)
            booking, was_created = Booking.objects.get_or_create(
                owner=users[owner],
                sitter=users[sitter],
                amount=Decimal(amount),
                defaults={
                    "start_date": start,
                    "end_date": start + timedelta(days=nights),
                    "status": status,
                },
            )
            if was_created:
                # created_at is auto_now_add, so backdate it with an update.
                Booking.objects.filter(pk=booking.pk).update(
                    created_at=now - timedelta(hours=hours_ago)
                )
                created += 1

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {len(SEED_BOOKINGS)} bookings ({created} new).")
        )
