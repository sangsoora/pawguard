# 0005. Message moderation: rules first, LLM only for ambiguous cases

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

We want to catch scams and attempts to move payment off the platform ("pay me on Bizum, I'll give
you a discount"). Most messages are harmless, so cost and latency matter. The text is written by
the people we are policing, so it is **untrusted input to anything that reads it**, including an
LLM. A wrong auto-flag hurts a real user; a miss lets a scam through. Nothing is enforced
automatically (ADR 0007).

## Decision

A two-stage pipeline (`apps/moderation/pipeline.py`):

1. **Rules** over normalised text (Unicode NFKC folding, zero-width characters removed).
   - A **strong** rule match (a narrow combination, e.g. payment app + "pay me / directly /
     outside the app", an IBAN, an overpayment pattern, a one-time-code request) -> `flagged`.
   - **No match** -> `clean`.
   - **Weak signals only** (a phone number, a payment app name, a link, an email) -> ambiguous.
2. **LLM**, only for ambiguous messages. It may **clear or flag** them. It can never override a
   strong rule, and it is never called for messages with no signals.

Safeguards:

- The message is passed as delimited data (`<message>...</message>`) with an instruction to
  ignore any instructions inside it. The LLM's answer is a validated structured output, not text
  we act on.
- **Fail safe to a human:** if the LLM is off, errors, refuses or returns unparsable output, the
  verdict is `needs_review` (stage `llm_unavailable`), never a silent "clean".
- The LLM stage is **opt-in** (`MODERATION_LLM_ENABLED` plus an API key) because it costs money.
  The model is configurable (`MODERATION_MODEL`, default `claude-opus-5-5`).
- Tokens and latency are stored per result and exported as metrics.

## Alternatives considered

- **LLM on every message:** best recall, but cost and latency scale with all traffic, and
  prompt injection becomes a primary attack surface.
- **Rules only:** cheap and fully predictable, but blind to anything phrased outside the patterns
  and noisy on weak signals.
- **A hosted moderation API:** convenient, but not tuned to marketplace-specific scams.
- **A trained classifier:** needs labelled data we do not have yet.

## Consequences

**Good:**

- Most messages never reach the LLM. On the evaluation set about 22% are ambiguous (10 of 46).
- A strong rule's decision is deterministic and cannot be talked out of by message content.
- Outages degrade to "more work for humans", not to missed or wrongly cleared messages.

**Costs and known gaps:**

- **Recall is bounded by the rules for messages with no trigger at all.** A novel scam phrased
  without any weak or strong signal is `clean` and never reaches the LLM. This is the main
  blind spot.
- Evasion is an arms race. NFKC and zero-width stripping help, but spaced-out letters
  ("p a y") and creative misspellings are not handled.
- `llm_unavailable` does not distinguish "not configured" from "failed".
- The default model is the most capable, not the cheapest. For volume, choose a smaller model
  and measure it with the eval (ADR 0006).

## Revisit when

Reviewed outcomes show missed scams that had no triggers (add a sampling pass of "clean" messages
through the LLM), or LLM spend becomes material.

## Code

- `apps/moderation/rules.py`, `apps/moderation/llm.py`, `apps/moderation/pipeline.py`
