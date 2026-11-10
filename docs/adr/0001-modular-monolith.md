# 0001. One repo, a modular Django monolith plus a React app

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

PawGuard is a Trust & Safety platform for a fictional pet-sitting marketplace: risk scoring,
message moderation, identity verification and a review console. It is built by one person and
the pieces share the same data (users, bookings) and the same guarantees (an audit entry must
exist if and only if the action happened). A single coherent system is also a better thing to
demo and explain than five small repos.

## Decision

- **One repository.** A Django project (`config/`) made of focused apps under `apps/`:
  `accounts`, `bookings`, `risk`, `moderation`, `verification`, `console` (the agent API) and
  `core` (audit, auth, metrics, permissions).
- **One React + TypeScript app** in `frontend/` (Vite). The same bundle serves two apps: the
  agent console at `/` and the owner/sitter app at `/account`.
- **Celery workers run the same codebase** as the web process.
- Apps may import each other's models and services, but keep their own models, tasks and tests.

## Alternatives considered

- **Microservices per domain** (risk, moderation, verification): independent scaling and
  deploys, but distributed transactions and an audit trail across services for no benefit at this
  size. Far more infrastructure than the problem needs.
- **Separate repos for frontend and backend:** more ceremony for a solo project; harder to keep
  API and UI changes in one reviewable change.
- **Server-rendered Django templates only:** quicker, but the console is a stateful, interactive
  tool and a React app shows the full-stack skill the work is meant to demonstrate.
- **Two separate SPA bundles:** cleaner separation, but double the build and config for a small UI.

## Consequences

**Good:**

- Changes and their audit entries commit in one database transaction.
- One deploy, one auth system, one place to refactor. Cross-cutting concerns (metrics, logging,
  request IDs) are written once.

**Costs and known gaps:**

- Module boundaries are enforced by convention only. `console` imports from nearly every app.
- The unit of scaling is the whole app, even if only moderation (LLM calls) is under load.
- Everyone downloads the console code, because both apps ship in one bundle.
- **Tests and local development use SQLite; production is expected to use Postgres.**
  `select_for_update()` is a no-op on SQLite, so the row-locking we rely on (state transitions,
  review actions) is not actually exercised by the tests. CI should run against Postgres.

## Revisit when

A domain needs to scale or deploy independently (most likely moderation under LLM load), or a
second developer joins and boundaries need enforcement.

## Code

- `config/settings/base.py` (installed apps), `apps/`, `frontend/src/main.tsx`
