"""Structured (JSON) logging with request and trace correlation."""

import json
import logging
from datetime import UTC, datetime

from opentelemetry import trace

from .context import request_id

# Attributes every LogRecord has; anything else was passed via `extra=` and is logged as a field.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class CorrelationFilter(logging.Filter):
    """Adds request_id and the active trace/span ids to every record."""

    def filter(self, record):
        record.request_id = request_id.get()
        ctx = trace.get_current_span().get_span_context()
        record.trace_id = f"{ctx.trace_id:032x}" if ctx.is_valid else None
        record.span_id = f"{ctx.span_id:016x}" if ctx.is_valid else None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_") and value is not None:
                entry[key] = value
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)
