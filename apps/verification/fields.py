"""Field-level encryption for PII (Fernet: AES-128-CBC + HMAC-SHA256, authenticated).

Keys come from settings.FIELD_ENCRYPTION_KEYS (newest first). Decryption tries every key, so
rotation is: prepend a new key, deploy, optionally re-save rows, then drop the old key.

Encrypted values cannot be filtered or ordered on (each encryption is randomised), so never
build lookups on these fields.
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _fernet() -> MultiFernet:
    keys = settings.FIELD_ENCRYPTION_KEYS
    if not keys:
        raise ImproperlyConfigured("Set FIELD_ENCRYPTION_KEYS to store encrypted fields.")
    return MultiFernet([Fernet(k) for k in keys])


class EncryptedTextField(models.TextField):
    description = "Text encrypted at rest with Fernet"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ImproperlyConfigured(
                "Could not decrypt a stored value: wrong or missing FIELD_ENCRYPTION_KEYS?"
            ) from exc
