"""Per-request context shared by logging and tracing."""

from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")
