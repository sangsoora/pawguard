"""The identity-verification provider boundary.

`MockProvider` stands in for a real KYC vendor. It never sees real documents. It returns a
reference on submit and later "calls back" via a signed webhook (see the
`simulate_provider_webhook` command). Swap `get_provider()` for a real client to go live; the
webhook contract in contracts/provider_webhook.schema.json stays the same.
"""

import json
import time
import uuid
from typing import Protocol

from django.conf import settings

from . import signing


class ProviderError(Exception):
    """Transient provider failure; the caller may retry."""


class Provider(Protocol):
    def submit(self, case) -> str: ...


class MockProvider:
    def submit(self, case) -> str:
        # Only non-PII metadata would go over the wire to a real vendor's API in addition to
        # the document images; the mock needs nothing.
        return f"mock_{uuid.uuid4().hex[:16]}"


def get_provider() -> Provider:
    return MockProvider()


def build_event(event_type: str, reference: str, *, reason: str = "", event_id: str | None = None):
    """Build a contract-conformant webhook body (what the provider would send)."""
    data = {"reference": reference}
    if reason:
        data["reason"] = reason
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "type": event_type,
        "created": int(time.time()),
        "data": data,
    }


def signed_request(payload: dict, secret: str | None = None) -> tuple[bytes, dict]:
    """Serialise and sign a webhook payload; returns (body, headers) ready to POST."""
    body = json.dumps(payload).encode()
    secret = settings.VERIFICATION_WEBHOOK_SECRET if secret is None else secret
    return body, {
        "Content-Type": "application/json",
        "X-Provider-Signature": signing.sign(secret, body),
    }
