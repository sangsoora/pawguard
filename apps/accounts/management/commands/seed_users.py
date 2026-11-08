from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User

R = User.Role

# (username, role, country, phone, signup_ip, extra)
AGENT_GROUP = "T&S Agents"
# Model permissions granted to agents: they can view and edit users/bookings, not delete.
AGENT_PERMISSIONS = [
    "view_user",
    "change_user",
    "view_booking",
    "change_booking",
]

SEED_USERS = [
    (
        "admin",
        R.AGENT,
        "ES",
        "+34600000000",
        "81.45.10.0",
        {"is_staff": True, "is_superuser": True},
    ),
    ("agent1", R.AGENT, "ES", "+34600000001", "81.45.10.1", {"is_staff": True}),
    ("agent2", R.AGENT, "ES", "+34600000002", "81.45.10.2", {"is_staff": True}),
    ("olivia", R.OWNER, "ES", "+34611111101", "88.12.5.20", {}),
    ("marc", R.OWNER, "ES", "+34611111102", "88.12.5.21", {}),
    ("sofia", R.OWNER, "FR", "+33611111103", "90.50.2.7", {}),
    ("lucas", R.OWNER, "DE", "+49151111104", "84.130.9.4", {}),
    ("emma", R.SITTER, "ES", "+34622222201", "88.12.7.30", {}),
    ("pablo", R.SITTER, "ES", "+34622222202", "88.12.7.31", {}),
    ("chloe", R.SITTER, "FR", "+33622222203", "90.50.3.8", {}),
    ("hans", R.SITTER, "DE", "+49152222204", "84.130.10.5", {}),
    # Deliberately suspicious accounts, handy for testing risk rules later:
    # declared country differs from signup IP origin, and both share a phone/IP.
    ("quickcash1", R.SITTER, "ES", "+4470000000099", "185.220.101.5", {}),
    ("quickcash2", R.SITTER, "ES", "+4470000000099", "185.220.101.5", {}),
    ("suspended_sam", R.SITTER, "US", "+15550000001", "203.0.113.9", {"status": "suspended"}),
]


class Command(BaseCommand):
    help = "Create (or update) sample users for local development. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="pawguard-dev", help="Password for all users")

    def handle(self, *args, password, **options):
        if not settings.DEBUG:
            raise CommandError("seed_users only runs with DEBUG=True.")

        group, _ = Group.objects.get_or_create(name=AGENT_GROUP)
        group.permissions.set(Permission.objects.filter(codename__in=AGENT_PERMISSIONS))

        created = 0
        for username, role, country, phone, ip, extra in SEED_USERS:
            user, was_created = User.objects.update_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.com",
                    "role": role,
                    "country": country,
                    "phone_number": phone,
                    "signup_ip": ip,
                    **extra,
                },
            )
            if was_created:
                user.set_password(password)
                user.save(update_fields=["password"])
                created += 1
            if role == R.AGENT:
                user.groups.add(group)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(SEED_USERS)} users ({created} new). "
                f"Password for new users: {password}"
            )
        )
