from django.core.management.base import BaseCommand

from apps.verification.tasks import resend_unsent


class Command(BaseCommand):
    help = (
        "Re-send verification submissions that never reached the provider (also runs on a timer)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-age", type=int, help="Only cases older than this many seconds (default: setting)"
        )

    def handle(self, *args, min_age, **options):
        result = resend_unsent(min_age)
        self.stdout.write(
            self.style.SUCCESS(
                f"Found {result['found']}, re-sent {result['sent']}, failed {result['failed']}."
            )
        )
