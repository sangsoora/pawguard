from django.core.management.base import BaseCommand

from apps.verification.services import purge_expired_documents


class Command(BaseCommand):
    help = "Blank personal data on decided verification cases older than the retention period."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, help="Override VERIFICATION_RETENTION_DAYS")

    def handle(self, *args, days, **options):
        n = purge_expired_documents(days)
        self.stdout.write(self.style.SUCCESS(f"Purged personal data from {n} case(s)."))
