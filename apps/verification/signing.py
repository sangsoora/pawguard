"""Webhook signatures: `X-Provider-Signature: t=<unix seconds>,v1=<hex hmac-sha256>`.

The signed string is `"<t>.<raw body>"`. The timestamp is inside the signature so a captured
request cannot be replayed later, and the comparison is constant-time.
"""

import hashlib
import hmac
import time

TOLERANCE_SECONDS = 300


class InvalidSignature(Exception):
    pass


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    t = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={digest}"


def verify(secret: str, body: bytes, header: str, now: float | None = None) -> None:
    """Raise InvalidSignature unless the header is a fresh, correct signature of `body`."""
    if not secret:
        raise InvalidSignature("Webhook secret is not configured")  # fail closed
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        t = int(parts["t"])
        provided = parts["v1"]
    except (KeyError, ValueError, AttributeError) as exc:
        raise InvalidSignature("Malformed signature header") from exc
    current = time.time() if now is None else now
    if abs(current - t) > TOLERANCE_SECONDS:
        raise InvalidSignature("Timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise InvalidSignature("Signature mismatch")
