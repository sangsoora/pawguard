"""OpenTelemetry tracing setup.

Spans are always created (cheap no-ops without a provider); they are exported only when
OTEL_ENABLED is set. Point OTEL_EXPORTER_OTLP_ENDPOINT at a collector or Jaeger
(`docker compose -f docker-compose.observability.yml up`), e.g. http://localhost:4318.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)
_configured = False


def setup_telemetry() -> bool:
    """Install the tracer provider and auto-instrumentation once. Returns True if enabled."""
    global _configured
    if _configured or not settings.OTEL_ENABLED:
        return _configured

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
    )
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    DjangoInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    _configured = True
    logger.info(
        "OpenTelemetry enabled", extra={"otlp_endpoint": settings.OTEL_EXPORTER_OTLP_ENDPOINT}
    )
    return True
