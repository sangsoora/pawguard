# 0007. The system recommends, humans decide, every action is audited

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

A false positive in Trust & Safety is not a UI glitch: it can suspend a real sitter's income or
reject a real person's identity. Our detectors (rules, an LLM, a mock verification provider) are
imperfect and we have little ground truth. We also need to answer "who did this, when, and why?"
for any action taken on an account.

## Decision

- **Detectors only recommend.** The risk engine produces an assessment with a score and
  decision, the moderation pipeline a verdict, the provider a verification result. **Nothing
  auto-suspends, auto-cancels or auto-blocks.** The `block` decision (score >= 80) is a priority
  label for the queue, not an enforcement.
- **Agents act through the console API.** Resolve a risk item or message (cleared = false
  positive, confirmed = true positive), suspend/reinstate a user, request verification, and
  approve/reject a case in manual review.
- **Every action** writes an `AuditLog` row (actor, action, target, metadata) *in the same
  transaction* as the change, and increments a metric.
- **Accountability inputs are required:** suspending/reinstating needs a reason; confirming a
  violation needs a note; verification decisions need a reason.
- **Safe under concurrency and retries:** reviews lock the row and return `409` if already
  resolved; agents may only decide verification cases in `manual_review`, never ones the provider
  is still deciding; agent accounts cannot be suspended or verified from the console.
- Only users with role `agent` can use the console API.

## Alternatives considered

- **Auto-enforce above a threshold:** faster response, but turns every detector error into
  customer harm, and we cannot yet measure those errors well enough.
- **Two-person approval for destructive actions:** stronger, but heavy for the current scale.
- **No audit log:** cheaper, but indefensible in a system whose job is accountability.

## Consequences

**Good:**

- We can ship imperfect detectors safely; the worst outcome of a wrong flag is wasted review time.
- A complete, queryable record of agent actions, plus a human-readable verification timeline.
- Agent decisions become labelled data for improving the detectors.

**Costs and known gaps:**

- **Harm persists until an agent acts.** Hence the queue-age metric and alert (ADR 0011).
- Throughput is bounded by the number of reviewers.
- **The audit log is append-only by convention** (read-only in the admin), not by database
  permissions or hash chaining. **All agents have the same powers**: no roles, no four-eyes
  approval.
- Rule edits in the admin bypass this audit trail (ADR 0002).

## Revisit when

Review volume outgrows the team, or we have measured precision good enough to auto-hold the most
extreme cases (for example a confirmed shared-identifier ring). Add agent roles first.

## Code

- `apps/core/audit.py`, `apps/core/models.py` (`AuditLog`), `apps/core/permissions.py`
- `apps/console/views.py` (`resolve_review`, `_decide`, suspend/reinstate)
