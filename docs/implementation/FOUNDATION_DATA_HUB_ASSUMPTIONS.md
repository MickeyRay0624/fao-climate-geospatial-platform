# Foundation + Data Hub assumptions and reconciliations

Date: 2026-08-31

This file records choices made where the blueprint, handoff, and running repository were not identical. The least destructive interpretation was used.

| Topic | Observed state | Implementation decision |
|---|---|---|
| Repository history | The supplied directory was not a Git repository. | Initialise locally, commit an untouched baseline, then work on `refactor/platform-foundation-data-hub`; do not add a remote or change global Git identity. |
| Legacy schema ownership | Legacy SQLAlchemy models and data already existed in `public`; no Alembic state existed. | Use one adoption-safe Alembic revision that creates missing legacy tables only for clean bootstrap, never drops existing tables, then creates/backfills new schemas. |
| Suggested package layout | The blueprint suggested many domain packages; the application was a compact FastAPI module. | Preserve readable legacy code and introduce bounded files (`identity`, `authorization`, `datahub`, `jobs`, etc.) rather than a risky move-only rewrite. This is still a modular monolith. |
| Object endpoint naming | Existing code used `MINIO_ENDPOINT`; blueprint requires internal/public separation. | Retain legacy settings and add `OBJECT_STORE_INTERNAL_ENDPOINT` plus `OBJECT_STORE_PUBLIC_ENDPOINT`; only the public client signs browser URLs. |
| Multipart upload | Phase 1 source files are capped at 100 MiB and the implemented browser path uses single presigned PUT. | Provide a session/file abstraction capable of multiple files, but defer S3 multipart part orchestration until larger-file/raster scope. |
| Worker job taxonomy | The vertical slice can validate and register an uploaded file in one atomic domain task. | Implement authoritative `catalog:validate-version:v1`, covering ingest/checksum/scan/validation/registration as visible steps. Separate ingest and packaged-download jobs are deferred until independently useful. |
| Malware scanner | No ClamAV or approved external scanner was available. | Implement a scanner interface and an unmistakable development bypass. Health is warning-level; staging/production fail closed. Do not claim a clean production scan. |
| OIDC | No FAO issuer, audience, JWKS URL, or test token was provided. | Implement and test the validation/mapping boundary; keep local personas explicit. Production SSO integration remains pending. |
| Legacy uploader | Legacy metadata said `uploaded_by=Mickey Lei` but no stable email/IdP subject existed. | Create a named legacy attribution identity with deterministic local subject and no invented real email. |
| Catalog authority | Old catalog tables must remain for rollback evidence, yet new writes must not be duplicated. | Backfill into `catalog.*`; all new catalog mutations use it exclusively. Legacy catalogue reads are adapters and their former mutation URLs return `410 LEGACY_CATALOG_READ_ONLY`; analytical read tables remain for compatibility. |
| Initial investment load | The legacy UI previously persisted an analysis run during page initialisation. | Add a non-persistent `/api/analysis/preview` path so browsing does not alter history; explicit user runs still persist. |
| Archive semantics | Objects and referenced versions may not be deleted. | A dataset containing a published version must be deprecated first. Archive then cancels open review/upload work and marks every remaining non-archived version archived; it never physically removes catalog or quarantine objects. |
| Published immutability | Service-only checks would be bypassable by direct SQL. | Enforce version, asset, and representation immutability in PostgreSQL triggers in addition to API rules. |
| Review exception | A small pilot can place multiple roles on one person but still requires distinct actions. | Creator-as-sole-reviewer is blocked by default. An audited, non-empty exception reason is supported; publish remains a separate action and permission. |
| Admin data access | A technical platform administrator must not silently receive every data entitlement. | Roles contain explicit permissions; private resource reads still require ownership, assignment, or grant. There is no implicit `platform.admin` data bypass. |
| Extension module | Manifest exists but there is no approved field workflow. | Seed it as installed and disabled. The registry may expose its status but no fake business screen or advice workflow is provided. |
| E2E test evidence | Full API E2E leaves durable evidence and failure artifacts must not be deleted. | Archive temporary test datasets after negative/failure runs and retain their objects/audit. Successful E2E datasets remain active alongside the legacy dataset as explicit test evidence. |

## Product boundary

The term “platform” describes shared identity, governance, catalog, jobs, and application-module infrastructure. It does not assert real-time sensing, farm-scale simulation, a digital twin, crop/water models, or agronomic authority. The current investment results remain illustrative synthetic evidence only.

## Deferred decisions

- Exact FAO identity claims, workspace provisioning, group sync, and break-glass operational approval.
- Production scanner provider and quarantine retention schedule.
- Multipart/resumable strategy and limits for raster-scale assets.
- Public catalogue/anonymous access policy and SENSITIVE_FIELD handling beyond fail-closed rules.
- PostGIS row-level security; service authorization is authoritative for Phase 1.
- Managed cloud services, TLS/ingress, secret management, monitoring, and backup SLOs.
- Full investment-domain migration described in the next-phase recommendation.
