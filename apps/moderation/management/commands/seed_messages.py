from itertools import cycle

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.bookings.models import Booking
from apps.moderation.evaluation import load_dataset
from apps.moderation.models import Message


class Command(BaseCommand):
    help = (
        "Create sample chat messages from the labelled eval dataset on existing bookings "
        "(run seed_users and seed_bookings first). Each message is moderated on creation. "
        "Idempotent: a message with the same body on the same booking is skipped."
    )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_messages only runs with DEBUG=True.")
        bookings = list(Booking.objects.select_related("owner", "sitter").order_by("id"))
        if not bookings:
            raise CommandError("No bookings found. Run `seed_users` and `seed_bookings` first.")

        created = 0
        senders = cycle(["owner", "sitter"])
        for booking, case in zip(cycle(bookings), load_dataset(), strict=False):
            sender = getattr(booking, next(senders))
            _, was_created = Message.objects.get_or_create(
                booking=booking, sender=sender, body=case.text
            )
            created += was_created
        self.stdout.write(self.style.SUCCESS(f"Seeded messages ({created} new)."))
