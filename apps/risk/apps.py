from django.apps import AppConfig


class RiskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.risk"

    def ready(self):
        from . import signals  # noqa: F401
