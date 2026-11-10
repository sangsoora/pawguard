# 0009. Encrypt PII at rest, minimise who sees it, purge after retention

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

Verification collects a person's full name and identity document number. Holding this data is a
liability: a leaked database backup, a careless log line or an over-broad admin screen could
expose it. Privacy law and basic prudence say to keep the least data, for the shortest time, with
the fewest people able to see it.

## Decision

- **Encrypt at rest.** `full_name` and `document_number` use `EncryptedTextField`
  (`apps/verification/fields.py`): Fernet (authenticated AES) with `MultiFernet`, so keys can be
  rotated by prepending a new one to `FIELD_ENCRYPTION_KEYS`. Rows decrypt through the ORM only.
- **Keys come from the environment.** In DEBUG a key is derived from `SECRET_KEY` for
  convenience; outside DEBUG there is no default, and using an encrypted field without a key fails
  loudly.
- **Minimise exposure.** The user-facing API never returns PII. Agents see the name and a masked
  document number (last four characters). The Django admin does not show the fields. PII is not
  logged.
- **Retention.** A job (`purge_expired_documents`, daily via Celery beat or
  `purge_verification_documents`) blanks the name and document number on *decided* cases older
  than `VERIFICATION_RETENTION_DAYS` (default 30). The case, its state and its audit trail stay.
  The purge is itself recorded as a system event and is idempotent.
- The country code is stored in the clear (low sensitivity, useful for review).

## Alternatives considered

- **Plaintext with disk or database encryption only:** protects a stolen disk, not a leaked
  dump or an over-privileged query.
- **Database-side encryption (pgcrypto):** keeps keys near the data and ties us to Postgres.
- **KMS envelope encryption:** the right production answer; more setup than this stage justifies
  and needs a cloud account.
- **Store nothing, keep only the provider's reference:** the best privacy posture, but agents
  need to see what was submitted to resolve a manual review.

## Consequences

**Good:**

- A leaked backup or database dump does not expose the identity data.
- Key rotation is supported, and the data's lifetime is bounded and auditable.
- Agents get what they need to decide and little more.

**Costs and known gaps:**

- **The key sits in the application's environment**, so a compromised app can decrypt. No KMS
  or HSM.
- **Encrypted values cannot be searched.** Duplicate-document detection (a useful fraud signal)
  would need a blind index (a keyed hash stored alongside).
- **Abandoned cases keep PII indefinitely.** The purge only covers decided cases, so a
  `submitted` or `manual_review` case that never resolves is never cleaned up.
- In DEBUG, changing `SECRET_KEY` makes existing encrypted rows undecryptable.

## Revisit when

Moving to production (KMS-managed keys), adding duplicate-document detection (blind index), or a
compliance review (expire abandoned submissions).

## Code

- `apps/verification/fields.py`, `apps/verification/services.py` (`purge_expired_documents`)
- `apps/console/serializers.py` (masking), `apps/verification/admin.py`
