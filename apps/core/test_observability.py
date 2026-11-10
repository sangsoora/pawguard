import json
import logging
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from django.test import Client
from django.utils import timezone
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.core import audit, metrics
from apps.core.context import request_id
from apps.core.jsonlog import CorrelationFilter, JsonFormatter
from apps.risk.engine import score_booking
from apps.risk.models import RiskAssessment

ROOT = Path(__file__).resolve().parents[2]


def sample(name, **labels):
    return metrics.registry.get_sample_value(name, labels) or 0.0


@pytest.fixture
def booking(db):
    owner = User.objects.create_user("owner", "o@x.com", "pw", role=User.Role.OWNER)
    sitter = User.objects.create_user("sitter", "s@x.com", "pw", role=User.Role.SITTER)
    return Booking.objects.create(
        owner=owner,
        sitter=sitter,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        amount=Decimal("900.00"),
    )


# --- /metrics endpoint ---


def test_metrics_requires_token_when_configured(settings, db):
    settings.METRICS_TOKEN = "s3cret"
    c = Client()
    assert c.get("/metrics/").status_code == 403
    assert c.get("/metrics/", HTTP_AUTHORIZATION="Bearer wrong").status_code == 403
    ok = c.get("/metrics/", HTTP_AUTHORIZATION="Bearer s3cret")
    assert ok.status_code == 200 and b"pawguard_" in ok.content


def test_metrics_closed_outside_debug_without_token(settings, db):
    settings.METRICS_TOKEN = ""
    settings.DEBUG = False
    assert Client().get("/metrics/").status_code == 403
    settings.DEBUG = True
    assert Client().get("/metrics/").status_code == 200


# --- counters and gauges ---


def test_scoring_updates_metrics(booking):
    before_review = sample("pawguard_risk_assessments_total", decision="review")
    before_flags = sample("pawguard_flags_total", source="risk", kind="review")
    before_hits = sample("pawguard_rule_hits_total", rule="NEW_ACCOUNT_HIGH_VALUE", shadow="false")
    a = score_booking(booking)
    assert a.decision == "review"
    assert sample("pawguard_risk_assessments_total", decision="review") == before_review + 1
    assert sample("pawguard_flags_total", source="risk", kind="review") == before_flags + 1
    assert (
        sample("pawguard_rule_hits_total", rule="NEW_ACCOUNT_HIGH_VALUE", shadow="false")
        == before_hits + 1
    )


def test_agent_actions_are_counted(booking):
    agent = User.objects.create_user("agent", "a@x.com", "pw", role=User.Role.AGENT)
    before = sample("pawguard_agent_actions_total", action="user.suspend")
    audit.record(agent, "user.suspend", "user", booking.sitter_id, reason="x")
    assert sample("pawguard_agent_actions_total", action="user.suspend") == before + 1


def test_queue_gauges_report_size_and_age(booking):
    empty = sample("pawguard_review_queue_size", queue="risk")
    a = score_booking(booking)  # review decision, pending
    RiskAssessment.objects.filter(pk=a.pk).update(created_at=timezone.now() - timedelta(hours=2))
    assert sample("pawguard_review_queue_size", queue="risk") == empty + 1
    # the registry's collector runs at scrape time, so go through generate_latest
    from prometheus_client import generate_latest

    text = generate_latest(metrics.registry).decode()
    age = float(re.search(r'oldest_age_seconds\{queue="risk"\} ([\d.e+]+)', text).group(1))
    assert age >= 2 * 3600 - 5
    assert re.search(r'oldest_age_seconds\{queue="verification"\} 0\.0', text)  # empty -> 0


# --- middleware ---


def test_request_id_generated_echoed_and_validated(db):
    c = Client()
    generated = c.get("/health/")["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert c.get("/health/", HTTP_X_REQUEST_ID="trace-me-12345")["X-Request-ID"] == "trace-me-12345"
    replaced = c.get("/health/", HTTP_X_REQUEST_ID="bad id\nwith newline")["X-Request-ID"]
    assert replaced != "bad id\nwith newline" and re.fullmatch(r"[0-9a-f]{32}", replaced)


def test_http_metrics_use_route_pattern_not_raw_path(db):
    c = Client()
    before = sample("pawguard_http_requests_total", method="GET", route="health/", status="200")
    c.get("/health/")
    assert sample("pawguard_http_requests_total", method="GET", route="health/", status="200") == (
        before + 1
    )
    c.get("/api/console/users/12345/")  # 403 for anonymous, but must not create a per-id label
    routes = {
        m.labels["route"]
        for f in metrics.registry.collect()
        for m in f.samples
        if "route" in m.labels
    }
    assert not any("12345" in r for r in routes)


def test_access_log_is_structured_with_request_id(db, caplog):
    with caplog.at_level(logging.INFO, logger="pawguard.request"):
        Client().get("/health/", HTTP_X_REQUEST_ID="req-abc-12345")
    rec = next(r for r in caplog.records if r.name == "pawguard.request")
    assert (rec.method, rec.path, rec.status) == ("GET", "/health/", 200)
    assert rec.duration_ms >= 0


# --- JSON logging ---


def make_record(**extra):
    record = logging.LogRecord(
        "pawguard.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_json_formatter_emits_parseable_structured_lines():
    token = request_id.set("req-123456")
    try:
        record = make_record(score=40, rules=["A", "B"])
        CorrelationFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
    finally:
        request_id.reset(token)
    assert data["message"] == "hello world" and data["level"] == "INFO"
    assert data["request_id"] == "req-123456"
    assert data["score"] == 40 and data["rules"] == ["A", "B"]  # `extra` fields become keys
    assert data["ts"].endswith("+00:00")
    assert "trace_id" not in data  # no active span


def test_json_formatter_includes_exception_info():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    assert "ValueError: boom" in json.loads(JsonFormatter().format(record))["exc_info"]


# --- tracing ---


@pytest.fixture(scope="module")
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


def test_scoring_emits_span_with_attributes_and_logs_correlate(booking, spans, caplog):
    spans.clear()
    with caplog.at_level(logging.INFO, logger="apps.risk.engine"):
        score_booking(booking)
    span = next(s for s in spans.get_finished_spans() if s.name == "risk.score_booking")
    assert span.attributes["booking.id"] == booking.pk
    assert span.attributes["risk.decision"] == "review"
    assert "NEW_ACCOUNT_HIGH_VALUE" in span.attributes["risk.rules_hit"]


def test_log_records_carry_trace_ids_inside_a_span(spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("outer") as s:
        record = make_record()
        CorrelationFilter().filter(record)
        data = json.loads(JsonFormatter().format(record))
    assert data["trace_id"] == f"{s.get_span_context().trace_id:032x}"
    assert len(data["span_id"]) == 16


# --- dashboards and alerts must only reference metrics that exist ---


def _registered_metric_names():
    names = set()
    for family in metrics.registry.collect():
        names.add(family.name)
    return names


def _referenced_metrics(text):
    found = set(re.findall(r"\bpawguard_[a-z0-9_]+", text))
    return {re.sub(r"_(total|bucket|sum|count)$", "", n) for n in found}


def test_dashboard_only_queries_existing_metrics():
    dashboard = json.loads((ROOT / "observability/grafana/dashboards/pawguard.json").read_text())
    exprs = [t["expr"] for p in dashboard["panels"] for t in p.get("targets", [])]
    assert exprs, "dashboard has no queries"
    missing = _referenced_metrics(" ".join(exprs)) - _registered_metric_names()
    assert not missing, f"dashboard references unknown metrics: {missing}"
    ids = [p["id"] for p in dashboard["panels"]]
    assert len(ids) == len(set(ids))
    assert dashboard["uid"] == "pawguard-overview"


def test_alert_rules_are_well_formed_and_reference_real_metrics():
    path = ROOT / "observability/grafana/provisioning/alerting/rules.yml"
    config = yaml.safe_load(path.read_text())
    rules = [r for g in config["groups"] for r in g["rules"]]
    assert {r["uid"] for r in rules} >= {"pg-review-queue-age", "pg-webhook-bad-signature"}
    for rule in rules:
        assert rule["condition"] in {d["refId"] for d in rule["data"]}
        assert rule["labels"]["severity"] and rule["annotations"]["summary"]
    missing = _referenced_metrics(path.read_text()) - _registered_metric_names()
    assert not missing, f"alert rules reference unknown metrics: {missing}"


def test_provisioned_datasource_uid_matches_dashboard_and_alerts():
    ds = yaml.safe_load(
        (ROOT / "observability/grafana/provisioning/datasources/prometheus.yml").read_text()
    )
    uid = ds["datasources"][0]["uid"]
    dashboard = json.loads((ROOT / "observability/grafana/dashboards/pawguard.json").read_text())
    assert {p["datasource"]["uid"] for p in dashboard["panels"] if "datasource" in p} == {uid}
    alerts = (ROOT / "observability/grafana/provisioning/alerting/rules.yml").read_text()
    assert f"datasourceUid: {uid}" in alerts


def test_route_label_tidies_regex_routes():
    from types import SimpleNamespace

    from apps.core.middleware import route_label

    m = SimpleNamespace(route="api/console/^users/(?P<pk>[^/.]+)/$")
    assert route_label(m) == "api/console/users/<pk>/"
    assert route_label(SimpleNamespace(route="health/")) == "health/"
    assert route_label(None) == "unmatched"
