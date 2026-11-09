from django.db import migrations

DEFAULT_RULES = [
    {
        "code": "NEW_ACCOUNT_HIGH_VALUE",
        "name": "New account, high-value booking",
        "evaluator": "new_account_high_value",
        "params": {"max_account_age_days": 7, "min_amount": 500},
        "points": 40,
        "mode": "active",
    },
    {
        "code": "BOOKING_VELOCITY",
        "name": "Too many bookings in a short window",
        "evaluator": "booking_velocity",
        "params": {"window_minutes": 60, "max_bookings": 3},
        "points": 40,
        "mode": "active",
    },
    {
        "code": "SITTER_SUSPENDED",
        "name": "Sitter account is suspended",
        "evaluator": "sitter_suspended",
        "params": {},
        "points": 60,
        "mode": "active",
    },
    {
        # Ships in shadow mode: recorded on every assessment but does not move the score
        # until promoted to active in the admin.
        "code": "SHARED_IDENTIFIERS",
        "name": "Sitter shares phone/IP with other accounts",
        "evaluator": "shared_identifiers",
        "params": {"min_linked_accounts": 1},
        "points": 30,
        "mode": "shadow",
    },
]


def create_rules(apps, schema_editor):
    Rule = apps.get_model("risk", "Rule")
    for data in DEFAULT_RULES:
        Rule.objects.update_or_create(code=data["code"], defaults=data)


class Migration(migrations.Migration):
    dependencies = [("risk", "0001_initial")]

    operations = [migrations.RunPython(create_rules, migrations.RunPython.noop)]
