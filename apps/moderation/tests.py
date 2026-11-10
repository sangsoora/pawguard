import json
from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.moderation.evaluation import evaluate, load_dataset
from apps.moderation.llm import (
    AnthropicClassifier,
    ClassifierError,
    LLMResult,
    get_classifier,
)
from apps.moderation.models import Message, ModerationResult
from apps.moderation.pipeline import classify_text, moderate_message
from apps.moderation.rules import has_phone_number, normalize, run_rules

V = ModerationResult.Verdict


class FakeClassifier:
    """Deterministic stand-in for the LLM stage; records what it was asked."""

    def __init__(self, flagged=False, fail=False):
        self.flagged, self.fail, self.calls = flagged, fail, []

    def classify(self, text):
        self.calls.append(text)
        if self.fail:
            raise ClassifierError("boom")
        return LLMResult(
            flagged=self.flagged,
            categories=["scam"] if self.flagged else [],
            confidence=0.8,
            reason="fake",
            model="fake",
            input_tokens=100,
            output_tokens=10,
            latency_ms=50,
        )


# --- rules (stage 1) ---


@pytest.mark.parametrize(
    "text",
    [
        "Pay me on Bizum and I'll give you a discount",
        "Send the money to my PayPal directly",
        "Let's talk outside the app on WhatsApp",
        "I overpaid, please send back the difference",
        "share the verification code we sent you",
        "ＰＡＹ ＭＥ on ＢＩＺＵＭ",  # fullwidth
        "p​a​y me on zelle instead",  # zero-width characters
    ],
)
def test_strong_rules_flag_without_llm(text):
    llm = FakeClassifier(flagged=False)  # would "clear" it if it were ever asked
    outcome = classify_text(text, llm)
    assert outcome.verdict == V.FLAGGED and outcome.stage == "rules"
    assert llm.calls == []  # the LLM can never override a strong rule


@pytest.mark.parametrize(
    "text",
    [
        "Can you send me photos of Max?",
        "Please pay attention to her paw",
        "Booking confirmed for 2026-12-01 to 2026-12-03",
    ],
)
def test_ordinary_messages_are_clean_and_skip_llm(text):
    llm = FakeClassifier()
    assert classify_text(text, llm).verdict == V.CLEAN
    assert llm.calls == []


def test_phone_detection_ignores_dates():
    assert has_phone_number("call 612 998 877 please")
    assert has_phone_number("+34 600-123-456")
    assert not has_phone_number("from 2026-12-01 to 2026-12-03")
    assert not has_phone_number("she is 12 and weighs 30 kilos")


def test_normalize_folds_unicode_and_invisible_characters():
    assert normalize("ＰＡＹ​ ME") == "pay me"


def test_rule_matches_explain_themselves():
    codes = {m.code for m in run_rules("whatsapp me, my email is a@b.com")}
    assert {"MESSAGING_APP", "EMAIL_ADDRESS"} <= codes


# --- pipeline (stage 2) ---


AMBIGUOUS = "My number is 612 998 877, call me when you're outside the house."


def test_ambiguous_goes_to_llm_and_can_be_cleared():
    llm = FakeClassifier(flagged=False)
    outcome = classify_text(AMBIGUOUS, llm)
    assert len(llm.calls) == 1
    assert (outcome.verdict, outcome.stage) == (V.CLEAN, "llm")


def test_ambiguous_flagged_by_llm_keeps_rule_categories():
    outcome = classify_text(AMBIGUOUS, FakeClassifier(flagged=True))
    assert outcome.verdict == V.FLAGGED and outcome.stage == "llm"
    assert "scam" in outcome.categories and "off_platform_contact" in outcome.categories
    assert any(r.startswith("LLM:") for r in outcome.reasons)


def test_ambiguous_without_llm_goes_to_humans():
    outcome = classify_text(AMBIGUOUS, None)
    assert (outcome.verdict, outcome.stage) == (V.NEEDS_REVIEW, "llm_unavailable")


def test_llm_failure_fails_safe_to_human_review():
    outcome = classify_text(AMBIGUOUS, FakeClassifier(fail=True))
    assert outcome.verdict == V.NEEDS_REVIEW


def test_llm_stage_is_off_by_default(settings, monkeypatch):
    settings.MODERATION_LLM_ENABLED = False
    assert get_classifier() is None
    settings.MODERATION_LLM_ENABLED = True
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert get_classifier() is None  # enabled but no key


# --- Anthropic classifier against a mocked HTTP transport ---


def _mock_client(handler):
    import anthropic
    import httpx2 as httpx

    return anthropic.Anthropic(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _message_response(payload, stop_reason="end_turn"):
    import httpx2 as httpx

    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 321, "output_tokens": 45},
        },
    )


def test_anthropic_classifier_request_and_parsing():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return _message_response(
            {"flagged": True, "categories": ["scam"], "confidence": 1.7, "reason": "phishing"}
        )

    result = AnthropicClassifier(client=_mock_client(handler)).classify("click this link")
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"  # structured output
    assert "temperature" not in body and "thinking" not in body  # removed/unsupported params
    # user text is passed as delimited, untrusted data
    assert body["messages"][0]["content"] == "<message>\nclick this link\n</message>"
    assert result.flagged and result.categories == ["scam"]
    assert result.confidence == 1.0  # clamped
    assert (result.input_tokens, result.output_tokens) == (321, 45)
    assert result.latency_ms is not None


def test_anthropic_classifier_maps_api_errors_to_classifier_error():
    import httpx2 as httpx

    def handler(request):
        return httpx.Response(
            500, json={"type": "error", "error": {"type": "api_error", "message": "x"}}
        )

    client = _mock_client(handler)
    client.max_retries = 0
    with pytest.raises(ClassifierError):
        AnthropicClassifier(client=client).classify("hello")


def test_anthropic_classifier_maps_refusal_to_classifier_error():
    def handler(request):
        return _message_response({}, stop_reason="refusal")

    with pytest.raises(ClassifierError):
        AnthropicClassifier(client=_mock_client(handler)).classify("hello")


# --- persistence + signal ---


@pytest.fixture
def booking(db):
    owner = User.objects.create_user("owner", "o@x.com", "pw", role=User.Role.OWNER)
    sitter = User.objects.create_user("sitter", "s@x.com", "pw", role=User.Role.SITTER)
    return Booking.objects.create(
        owner=owner,
        sitter=sitter,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        amount=Decimal("50.00"),
    )


def test_moderate_message_stores_llm_cost_and_latency(booking):
    msg = Message.objects.create(booking=booking, sender=booking.owner, body=AMBIGUOUS)
    result = moderate_message(msg, FakeClassifier(flagged=True))
    assert result.verdict == V.FLAGGED
    assert (result.llm_model, result.llm_input_tokens, result.llm_output_tokens) == (
        "fake",
        100,
        10,
    )
    assert result.llm_latency_ms == 50 and result.review_status == "pending"


def test_new_message_is_moderated_after_commit(booking, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        msg = Message.objects.create(
            booking=booking, sender=booking.sitter, body="Pay me on Bizum, no app needed"
        )
    assert msg.moderation.verdict == V.FLAGGED
    assert "off_platform_payment" in msg.moderation.categories


def test_moderation_is_idempotent(booking, django_capture_on_commit_callbacks):
    from apps.moderation.tasks import moderate

    with django_capture_on_commit_callbacks(execute=True):
        msg = Message.objects.create(booking=booking, sender=booking.owner, body="hello there")
    assert moderate(msg.pk) is None  # already moderated
    assert ModerationResult.objects.filter(message=msg).count() == 1


# --- evaluation harness + CI regression gate ---


def test_eval_dataset_is_balanced_and_well_formed():
    cases = load_dataset()
    labels = [c.label for c in cases]
    assert set(labels) == {"flag", "clean"}
    assert labels.count("flag") >= 15 and labels.count("clean") >= 15
    assert len({c.text for c in cases}) == len(cases)  # no duplicates


def test_eval_gate_rules_only():
    """Regression gate for CI: rules-only quality must not drop below these floors.

    Auto-flags must be near-perfect (a wrong auto-flag hurts a real user); everything
    suspicious must still reach a human (overall recall).
    """
    report = evaluate(load_dataset(), classifier=None)
    assert report.auto.precision >= 0.95, report.errors
    assert report.auto.recall >= 0.75
    assert report.overall.recall >= 0.95, report.errors
    assert report.llm["calls"] == 0


def test_eval_with_perfect_llm_improves_precision_and_reports_cost(settings):
    class Oracle:
        """Pretends to be a perfect LLM by looking up the dataset label."""

        def __init__(self):
            self.labels = {c.text: c.label == "flag" for c in load_dataset()}

        def classify(self, text):
            flagged = self.labels[text]
            return LLMResult(
                flagged, ["scam"] if flagged else [], 0.9, "oracle", "oracle", 200, 20, 400
            )

    base = evaluate(load_dataset(), None)
    with_llm = evaluate(load_dataset(), Oracle())
    assert with_llm.overall.precision > base.overall.precision
    assert with_llm.overall.recall == 1.0 and with_llm.routing["needs_review"] == 0
    assert with_llm.llm["calls"] == base.routing["needs_review"]  # only ambiguous cases pay
    assert with_llm.llm["est_cost_usd"] > 0 and with_llm.llm["avg_latency_ms"] == 400


def test_seed_messages_idempotent(db, settings, django_capture_on_commit_callbacks):
    from django.core.management import call_command

    settings.DEBUG = True
    call_command("seed_users")
    call_command("seed_bookings")
    with django_capture_on_commit_callbacks(execute=True):
        call_command("seed_messages")
    n = Message.objects.count()
    call_command("seed_messages")
    assert Message.objects.count() == n == len(load_dataset())
    assert ModerationResult.objects.filter(verdict=V.FLAGGED).exists()
    assert ModerationResult.objects.filter(verdict=V.NEEDS_REVIEW).exists()
