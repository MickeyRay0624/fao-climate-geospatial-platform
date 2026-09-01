# Foundation + Data Hub Core implementation

Date: 2026-08-31
Branch: `refactor/platform-foundation-data-hub`
Scope: Phase 1 runnable increment

## Delivered outcome

The repository now runs as the **FAO Climate Geospatial Data & Decision Platform** while retaining the original Cambodia commune rice prioritisation workflow as the enabled `investment-prioritisation` module. All new catalog writes use `catalog.*`; legacy analytical tables remain available and unchanged as a compatibility read model.

The implemented end-to-end path is:

```text
contributor creates private dataset/version
→ API returns short-lived presigned MinIO PUT into quarantine
→ completion creates a durable processing job
→ Celery worker checks object, SHA-256, scan policy, and validation profile
→ validated asset is copied to catalog storage and quality evidence is recorded
→ contributor submits a typed review
→ independently scoped reviewer approves
→ publisher freezes metadata and publishes
→ viewer with an allow grant can preview/download
→ every material action is visible in append-only audit and lineage
```

## Backend

- `api/app/platform_models.py` defines namespaced identity, workspace, governance, catalog, job, audit, integration, and investment entities.
- Alembic revision `20260831_0001` creates the eight schemas/tables and core triggers; `20260831_0002` adds lifecycle checks and hardens published child records, review decisions, and audit evidence. The post-migration idempotent seed creates deterministic backfill mappings and catalog rows.
- `api/app/identity.py` exposes a provider-neutral `Principal`, a development provider, and OIDC JWT/JWKS validation.
- `api/app/authorization.py` applies active identity/membership, permission, visibility/classification, ownership/grant, assignment, explicit-deny, state, and separation-of-duties checks.
- `api/app/module_registry.py` validates version-controlled YAML module manifests against the blueprint JSON Schema before enablement.
- `api/app/datahub/router.py` exposes the versioned Data Hub lifecycle and governed read endpoints.
- `api/app/datahub/validators.py` provides the four Phase 1 profiles and a scanner abstraction.
- `api/app/jobs.py` runs `catalog:validate-version:v1`; PostgreSQL is authoritative for user-visible status while Redis/Celery transports work.
- `api/app/audit_service.py` writes structured, redacted audit events; the database rejects update/delete.
- `api/app/errors.py` and middleware in `api/app/main.py` provide stable error codes and correlation IDs.

The legacy read routes are retained as adapters over `catalog.*` and deterministic legacy mappings. Former legacy catalogue upload/publish mutations now return `410 LEGACY_CATALOG_READ_ONLY`, so there is one write authority. Initialising the investment page uses non-persistent preview so navigation cannot create an analysis run. Ranking, map, explanations, quality information, published selection, CSV export, and GeoJSON export remain compatible.

## Frontend

- React Router isolates platform and application-module routes.
- The application shell obtains navigation and feature flags from `/api/me/capabilities` and shows workspace, user, jobs, breadcrumbs, and a prominent development-identity warning.
- Data Hub pages include catalogue/search/filter views, My Data, an eight-stage upload wizard, dataset/version details, quality, review, access, lineage, jobs, and download actions.
- Governance supplies members, groups, roles, dataset grants, module status, and read-only audit views sufficient for Phase 1 demonstration.
- Hidden actions reflect capabilities, but all access control is independently enforced by the API.
- The legacy investment page is lazy-loaded at `/apps/investment-prioritisation/overview` and retains its synthetic/not-operational disclaimer.

Browser QA at 1440×900 and 390×844 verified the shell, catalogue, dataset/version details, upload wizard, audit, persona switching, review queue, and investment map/ranking. It exposed and led to fixes for unsaved-preview export links, the missing `eligible` response field, and review audit IDs. No browser console errors or horizontal overflow remained.

## Database and storage

The migration creates `iam`, `core`, `governance`, `catalog`, `jobs`, `audit`, `integration`, and `investment`. Published version business fields, assets, and representations are protected by database triggers as well as service checks. `audit.events` is database-enforced append-only.

Legacy integer IDs are mapped to deterministic UUID5 values in `integration.legacy_id_mappings`. The original object remains at:

```text
datasets/1/versions/1/cambodia-rice-priority-synthetic-v1.geojson
```

New uploads follow:

```text
quarantine/{workspace_id}/{upload_session_id}/{file_id}
catalog/{workspace_id}/datasets/{dataset_id}/versions/{version_id}/source/{file_id}
```

Failed source material remains traceable in quarantine; archive is a lifecycle action and does not physically delete source objects.

## Operational behavior

Compose starts in dependency order: PostGIS/MinIO/Redis → Alembic → idempotent seed → API/worker/web. API and worker images run as non-root application users. Configuration fails closed when production/staging attempts to enable development headers or the insecure scanner bypass.

## Verification evidence

- Pre-change backend: 6 tests passed; frontend production build passed.
- Final backend suite: 34 tests passed.
- Final frontend component suite: 8 tests passed.
- TypeScript and Vite production build passed; npm audit reported 0 vulnerabilities.
- Existing database upgraded; a second Alembic upgrade was a no-op.
- Clean temporary database upgraded through both revisions, seeded twice, and verified at head with eight schemas and eight protection triggers, then removed.
- The pre-change dump restored into a temporary database with exact legacy counts, then the temporary database was removed.
- Database guard script proved audit/review append-only behavior plus published version, metadata, and asset immutability.
- Positive Data Hub E2E (`20260831-051029`) and negative authorization/lifecycle controls (`20260831-051031`) passed.
- Legacy regression remained: 111 areas, 777 indicators, 13 historical runs, 1,443 results; rank 1 stayed Prey Veng Demo Commune 03 at 65.32.

See `MIGRATION_RECONCILIATION.md` for the exact before/after ledger and runbooks for repeatable commands.

## Production integration still pending

FAO IdP values and claim conventions must be supplied and tested by the identity owner. A FAO-approved malware scanner must replace the local bypass. TLS, managed secrets, backups/retention, observability, ingress, disaster recovery objectives, and production infrastructure remain deployment work. These are not represented as complete.
