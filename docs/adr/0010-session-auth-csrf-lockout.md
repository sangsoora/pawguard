# 0010. Session cookies, CSRF and lockout for the SPAs; two separate login doors

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

Two audiences use the React app: Trust & Safety agents (powerful, can suspend accounts) and
marketplace users (owners and sitters, who can submit identity details). Both log in over JSON
because the SPA cannot use Django's HTML login form. Login endpoints are the front door for
credential stuffing and brute force, and agent accounts are high-value targets. We also hit a
real bug: on `localhost`, other local projects share the default `csrftoken` and `sessionid`
cookies (cookies ignore ports), which broke login.

## Decision

- **Server-side sessions in cookies plus Django CSRF** (double-submit token in
  `X-CSRFToken`), over same-origin JSON endpoints. In development Vite proxies `/api` to Django so
  it is same-origin; `CSRF_TRUSTED_ORIGINS` allows the dev origin in local settings only.
- **App-specific cookie names** (`pawguard-csrftoken`, `pawguard-sessionid`) so another local
  project cannot shadow them.
- **Login protection** (`apps/core/auth.py`):
  - a per-IP throttle (20 login requests a minute), and
  - a lockout per (door, username, IP): 5 failures lock that combination for 15 minutes, checked
    **before** `authenticate()` so even the right password is refused while locked. Counters live in
    the Django cache (Redis when configured).
  - unknown usernames count too, and bad credentials and "wrong kind of account" return the same
    message, so accounts cannot be enumerated.
- **Two doors, one implementation:** the console login accepts only agents, the account login only
  owners and sitters, each with its own counters. Permission classes (`IsTrustAgent`,
  `IsMarketplaceUser`) keep the roles apart on every endpoint. Suspended users are refused, after
  a correct password.
- CSRF failures on API paths return JSON with the reason, and the client retries once after
  refreshing the token.

## Alternatives considered

- **JWT in `localStorage`:** readable by any XSS, hard to revoke. Cookies with CSRF keep tokens
  out of JavaScript.
- **OAuth/OIDC single sign-on for agents:** the right production answer for staff; heavier than
  this stage needs.
- **`django-axes` or a proxy-level rate limiter:** capable, but we wanted small, tested, readable
  logic that we control.
- **One shared login for everyone:** simpler, but mixes agent and user privileges behind one
  door.

## Consequences

**Good:**

- No credentials or tokens in JavaScript; sessions can be revoked server-side; CSRF protection is
  built in.
- Brute force and spraying are both limited, with metrics (`pawguard_login_failures_total`).
- An agent session cannot reach the user app and vice versa.

**Costs and known gaps:**

- **No multi-factor authentication for agents**, who hold the most powerful accounts.
- **No global per-username cap.** A distributed attacker using many IPs against one username is
  limited only by the per-IP throttle.
- Without Redis the cache is per process, so lockout does not hold across several workers.
- Behind a reverse proxy, `REMOTE_ADDR` must be the real client IP, or all users share one
  counter.
- Cookie sessions tie the SPA to the same site (or careful CORS/CSRF configuration).
- No sign-up or password-reset flow yet.

## Revisit when

Before real agents use it: add MFA or SSO. Also when deploying behind a proxy (trusted-proxy
config) or running several workers (require Redis).

## Code

- `apps/core/auth.py`, `apps/console/auth.py`, `apps/accounts/api.py`, `apps/core/permissions.py`
- `config/settings/base.py` (cookie names, throttle and lockout settings), `frontend/src/api.ts`
