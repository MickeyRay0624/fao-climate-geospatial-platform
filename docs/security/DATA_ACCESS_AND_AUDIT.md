# Data access and audit

## Enforcement model

The browser is not a security boundary. Every mutation and sensitive read is re-authorized in FastAPI. The effective decision is fail-closed and follows:

```text
active identity
→ active, unexpired workspace membership
→ enabled module and application entitlement
→ classification/visibility ceiling
→ explicit DENY (wins immediately)
→ ownership, assignment, or active user/group grant
→ role permission
→ lifecycle/resource constraint
→ separation of duties
→ ALLOW; otherwise deny without confirming resource existence
```

`platform.admin` is not a hidden entitlement to all private datasets. Technical administration and content access are separate.

## Visibility and classification

Visibility values are `PRIVATE`, `RESTRICTED`, `WORKSPACE`, `TEAM`, `FAO_INTERNAL`, and `PUBLIC`. Classification values are `PUBLIC`, `FAO_INTERNAL`, `RESTRICTED`, and `SENSITIVE_FIELD`.

New datasets default to private. Classification is a ceiling: sensitive/restricted material cannot be made more public than policy permits. Phase 1 does not expose anonymous public access; `PUBLIC` describes catalog policy inside the authenticated platform boundary until a separately reviewed public gateway exists.

## Resource grants

An owner or actor with `dataset.manage_access` can grant a user or group a permission code with:

- `ALLOW` or `DENY` effect;
- optional expiration;
- mandatory reason;
- resource/workspace scope;
- actor and timestamps.

Expired grants do not apply. Any matching explicit deny takes precedence over role, ownership, group, or allow grants. Preview and download re-evaluate policy each time; a previously issued URL expires and is not a durable entitlement.

## Lifecycle and duties

- Creator/upload owner can submit but cannot be the only reviewer by default.
- Review decisions are append-only and retain type, rationale, checklist snapshot, actor, timestamp, and any exception reason.
- Reviewer permission does not imply publisher permission.
- Publish requires an approved version, completed required review, no blocking quality issue, required metadata, acceptable scan state, and optimistic row version.
- Published metadata snapshot, version business fields, assets, and representations are immutable. Corrections require a new version.
- Deprecation and archive retain objects, lineage, reviews, jobs, and audit evidence.

## Download and preview

Authorized downloads return a short-lived MinIO GET URL and expiry, never a permanent access/secret key. Unauthorized responses do not reveal object keys. Sensitive previews and every download request create audit records. The local presign TTL defaults to 900 seconds and is configurable.

Direct vector ingestion preserves the original ZIP/GeoPackage and stores any derived GeoJSON under a separate role, key and checksum. Source and derived downloads are independently selected but pass through the same authorization and audit boundary.

## Extension field evidence

Extension case reads are workspace- and assignment-aware. A supervisor has a wider operational view; an officer does not gain access to another officer's case merely by knowing an identifier. Completed observations/history are database-protected, and mutations require idempotency keys.

Field images are `SENSITIVE_FIELD`, type/size bounded and stored under case-scoped object keys. Viewing requires `extension.media.view_sensitive`, an acceptable scan status and a new short-lived URL, and generates audit evidence. The service worker excludes Extension API and media responses from caching. The local scanner bypass remains a visible warning and cannot be enabled in production/staging.

## Audit contents

`audit.events` records UTC time, workspace, actor, action, resource type/ID, outcome, reason, before/after summaries, correlation ID, and request context. Material events include:

- identity context resolution;
- dataset/version/upload lifecycle;
- processing success/failure and retry;
- review request/decision and duty exceptions;
- publication, deprecation, and archive;
- preview/download;
- grant create/delete including deny;
- module enable/disable;
- denied sensitive actions and future break-glass use.

Sensitive keys, credentials, bearer tokens, and signed query values are redacted before storage. Audit search itself requires `audit.view`; viewer denial and auditor access are covered by tests.

The governance audit view supports actor, action, resource, outcome, correlation-ID and UTC date filters plus a bounded CSV export. Administrative membership/group/role changes, knowledge decisions, application posture and permission denials are included in the same append-only evidence model.

## Append-only guarantee

The application exposes no audit update/delete endpoint. PostgreSQL also installs a trigger that rejects `UPDATE` and `DELETE` against `audit.events`. The guard is exercised by `scripts/verify_database_guards.sql` so direct ORM/SQL mistakes cannot silently rewrite history.

Database superusers and infrastructure administrators remain outside the application threat boundary. Production requires restricted database roles, central log export/WORM retention, database activity monitoring, and alerting for privileged access.

## Correlation and incident use

Every request receives or generates a correlation ID, returned in the response and copied into logs/audit. Investigators should search by correlation ID, then resource ID/action/actor and UTC range. Do not alter records during an investigation; capture database/object snapshots according to the backup runbook.

## Production controls still required

- FAO-approved data-classification mapping and public-release process;
- retention/deletion/legal-hold schedules by data class;
- approved scanner and quarantine release procedure;
- managed identity/group lifecycle and access recertification;
- database least-privilege roles and possibly Postgres RLS as defense in depth;
- centralized immutable audit export, SIEM alerts, and privacy review;
- key/secret rotation, TLS, secure ingress, rate limiting, and signed-URL policy review.
