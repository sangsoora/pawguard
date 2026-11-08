from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Marketplace user. Email is unique; role drives permissions and risk rules."""

    class Role(models.TextChoices):
        OWNER = "owner", "Pet owner"
        SITTER = "sitter", "Pet sitter"
        AGENT = "agent", "Trust & Safety agent"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OWNER)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    phone_number = models.CharField(max_length=32, blank=True)
    # ISO 3166-1 alpha-2 country declared on the profile; compared with IP country in risk rules.
    country = models.CharField(max_length=2, blank=True)
    signup_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["role", "status"])]

    def __str__(self):
        return self.email or self.username
