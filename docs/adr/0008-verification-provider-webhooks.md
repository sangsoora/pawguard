# 0008. Identity verification: provider boundary, signed idempotent webhooks, schema contract

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

Identity verification is done by an external provider that decides asynchronously and reports back
by webhook. Webhook endpoints are public, so anyone can POST to them. Providers retry on failure,
deliver duplicates and can deliver events out of order. A forged "approved" event would grant
verified status. We also want to build and test the whole flow before choosing a real vendor.

## Decision

- **State machine** (`apps/verification/services.py`): `requested -> submitted -> verified |
  rejected | manual_review -> verified | rejected`. Every change goes through `transition()`,
  which locks the row, rejects illegal moves and writes an append-only `VerificationEvent`
  (who, source, why).
- **Provider boundary:** `provider.get_provider()` returns a `MockProvider`. A real vendor
  replaces it behind the same interface. Submission runs as a retrying, idempotent task; a
  periodic sweeper re-sends submissions that never got a provider reference.
- **Webhook authenticity:** HMAC-SHA256 over `"<timestamp>.<raw body>"` in
  `X-Provider-Signature: t=...,v1=...`, constant-time comparison, a 5-minute timestamp tolerance
  against replay, and **fail closed** when no secret is configured.
- **Contract:** `contracts/provider_webhook.schema.json` (JSON Schema). The consumer validates every
  body against it and rejects anything off-contract with `400`, even when correctly signed.
- **Idempotency:** each event id is stored once (`WebhookEvent.event_id` is unique). Duplicates
  return `200 duplicate`. Illegal or out-of-order transitions and unknown references return `200`
  (`ignored`, `unknown_case`) because a retry could never succeed; they are counted in metrics.
- **Manual review:** the provider can send `needs_review`; only then may an agent approve or
  reject (ADR 0007).

## Alternatives considered

- **Pact (consumer-driven contract tests):** tests actual interactions between two services. With
  a mock provider on the other side there is nothing to verify against yet, so a shared JSON Schema
  is the honest contract for now.
- **Polling the provider instead of webhooks:** simpler security, but slower and wasteful, and
  providers push.
- **Trusting the payload without a signature:** unacceptable for a public endpoint.
- **Processing webhooks on a queue:** more resilient to bursts, but harder to reason about
  ordering and unnecessary at this volume.

## Consequences

**Good:**

- Safe under duplicates, retries, reordering, tampering and replay, all covered by tests.
- The whole flow works end to end today (including a `simulate_provider_webhook` command) and can
  swap in a real vendor.

**Costs and known gaps:**

- **JSON Schema checks shape, not behaviour.** A real provider will also differ in signature
  format and event semantics, so an adapter and real contract tests are needed at integration.
- **One shared secret, no rotation.** Rotating it needs a deploy and a window of rejected events;
  accepting two secrets during a rotation is the fix.
- `WebhookEvent` grows without pruning.
- Returning `200` for `unknown_case` can hide mis-routed events; the metric and the alert on bad
  signatures/payloads are the safety net.

## Revisit when

Integrating a real provider (adapter, contract tests against its sandbox, secret rotation).

## Code

- `apps/verification/services.py`, `apps/verification/signing.py`, `apps/verification/provider.py`
- `apps/verification/api.py`, `apps/verification/tasks.py`
- `contracts/provider_webhook.schema.json`
