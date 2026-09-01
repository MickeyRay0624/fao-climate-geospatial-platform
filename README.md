# FAO Climate Geospatial Data & Decision Platform

This repository is a runnable platform increment: a shared application shell, governed geospatial Data Hub, and a natively governed Investment & Extension Prioritisation module for the preserved Cambodia rice-resilience demonstration.

The current Cambodia data are **synthetic demonstration data** for 111 illustrative communes. They are not official boundaries, observations, operational advice, a field-scale digital twin, or an endorsed FAO methodology.

## Implemented in this increment

- Responsive React application shell with capability-driven navigation, development-persona switcher, jobs, reviews, governance, audit, and help views.
- OIDC-ready identity boundary plus an explicitly labelled local development provider.
- Organizations, workspaces, memberships, groups, roles, permissions, resource grants, module registry, and workspace module enablement.
- Backend RBAC/ABAC authorization with ownership, review assignment, visibility/classification rules, and explicit `DENY` precedence.
- Versioned Data Hub APIs and the governed lifecycle from private draft through direct upload, background validation, review, immutable publication, sharing, preview/download, lineage, deprecation, and archive.
- Validation profiles for the legacy analysis bundle, generic GeoJSON, CSV tables, and basic documents.
- Celery/Redis jobs with durable PostgreSQL state, progress steps, retry rules, idempotency, and audit events.
- Alembic schemas for `iam`, `core`, `governance`, `catalog`, `jobs`, `audit`, `integration`, and the native `investment` domain.
- Strangler backfill of the existing catalog into the new authoritative `catalog.*` model without moving or modifying the original MinIO object.
- Locked exact-version input sets for both the legacy bundle and separate boundary plus seven indicator layers.
- Immutable method/scenario versions with separate editor and approver roles.
- Explicit Celery analysis runs with durable state, cancellation/failure evidence, deterministic results and idempotency.
- Native run history/detail, maps, contributions, comparison, audit, signed outputs and catalog lineage.
- Historical backfill of 13 legacy runs and 1,443 results with deterministic UUID mappings and exact row reconciliation.

Not implemented: production FAO SSO connection, an approved production malware scanner, cloud/public deployment, raster/COG/STAC processing, GeoParquet/PDF investment exports, the Extension Officer Field Support workflow, business endorsement of the method, LLM or agronomic advice.

## Local architecture

```text
Browser (React + TypeScript)
  ├─ /api ──────► FastAPI modular monolith
  │                ├─ PostgreSQL/PostGIS: authoritative metadata and read models
  │                ├─ MinIO: immutable source assets and quarantine objects
  │                └─ Redis ─► Celery worker: validation + geospatial-analysis queues
  └─ signed PUT/GET ─► MinIO (short-lived URLs; no permanent browser credentials)

Optional GeoServer ─────────► PostGIS publication layer
```

The new catalog is authoritative for dataset metadata and `investment.*` is authoritative for every new analysis run/result. Legacy `admin_areas`, `indicator_values`, `analysis_runs`, and `priority_results` remain unchanged read-only evidence during the strangler migration.
The legacy investment catalogue URLs remain as read adapters over the authoritative catalog and deterministic backfill mappings. Their former upload/publish mutations return `410 LEGACY_CATALOG_READ_ONLY`, preventing dual writes while preserving the existing UI contract.
The former legacy analysis mutation returns `410 LEGACY_ANALYSIS_READ_ONLY`; no compatibility flag permits dual writes.

## Start locally

Requirements: Docker Desktop with Docker Compose.

```bash
cd "/Users/lei/Documents/联合国工作/数字孪生/cambodia-rice-dss"
cp .env.example .env
docker compose up --build -d
docker compose ps -a
```

Compose waits for PostgreSQL, runs `alembic upgrade head`, executes the idempotent seed, and then starts the API, worker, and web application. Re-running the command is safe.

Open:

- Platform: <http://localhost:3001/home>
- Data Hub: <http://localhost:3001/data/catalog>
- Investment module: <http://localhost:3001/apps/investment-prioritisation/overview>
- OpenAPI: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- MinIO console: <http://localhost:9001>

The default host Web port is `3001`. Override it with `WEB_HOST_PORT=<port>` in the local `.env` file when needed; API CORS origins follow the selected port automatically. Vite continues to listen on port 3000 inside the private Docker network, which does not occupy the host's port 3000.

Stop containers without deleting data:

```bash
docker compose down
```

> **Data-preservation warning:** never run `docker compose down -v` for this project. It deletes the PostgreSQL, MinIO, and Redis volumes. Follow [BACKUP_AND_RESTORE.md](docs/runbooks/BACKUP_AND_RESTORE.md) before any migration or recovery operation.

## Development identities

Development mode is intentionally visible and is not FAO SSO. The seeded personas are:

| Subject | Persona | Role |
|---|---|---|
| `dev-admin` | Amina Sok | workspace administrator |
| `dev-contributor` | Dara Chann | contributor/data owner |
| `dev-reviewer` | Sophea Lim | reviewer |
| `dev-publisher` | Nita Vann | publisher |
| `dev-analyst` | Vichea Pen | spatial analyst |
| `dev-viewer` | Maly Chea | viewer |
| `dev-auditor` | Samnang Khem | auditor |
| `dev-method-editor` | Chantha Ros | investment method/scenario editor |
| `dev-method-approver` | Bopha Keo | independent investment method/scenario approver |

Use the banner switcher in the UI or send `X-Dev-User-Subject: <subject>` locally. The API refuses development identity headers outside `APP_ENV=development|test`; production/staging configuration fails closed. See [DEV_AUTH_AND_OIDC_BOUNDARY.md](docs/security/DEV_AUTH_AND_OIDC_BOUNDARY.md).

## Data Hub workflow

```text
create dataset → draft version → direct upload to quarantine
  → background scan/validation → quality evidence → independent review
  → publisher action → immutable published snapshot → governed access
```

Supported profiles:

- `analysis-ready-priority-bundle@1.0`: existing GeoJSON or CSV+WKT investment bundle rules;
- `administrative-boundary@1.0`: stable area identity and valid boundary geometry;
- `normalised-indicator-layer@1.0`: declared indicator metadata, join key, normalised values and coverage;
- `generic-vector@1.0`: non-empty GeoJSON `FeatureCollection` with geometry/schema summary;
- `generic-table@1.0`: parseable CSV with header/row/schema sampling;
- `document@1.0`: PDF, DOCX, Markdown, and text cataloging without OCR or content exposure.

Direct uploads use short-lived presigned URLs. In local development the scanner is an explicit `development scan bypass`; the health endpoint returns `healthy_with_warnings`. Staging and production cannot enable this bypass.

## Migrations and seed

```bash
make migrate
make seed
```

Alembic supports an existing legacy database and clean bootstrap. Head `20260831_0003` adds the native investment domain. Destructive downgrade is intentionally blocked and recovery uses paired database/object snapshots. Seed and investment backfill are idempotent and never overwrite a differing source object.

Run or re-verify the native historical migration:

```bash
docker compose run --rm --no-deps api \
  python -m app.investment.backfill_legacy --verify --materialise-outputs
```

## Verification

```bash
docker compose run --rm --no-deps api python -m pytest -q
npm --prefix web test
npm --prefix web run build
npm --prefix web audit
python scripts/e2e_datahub.py
python scripts/e2e_negative_controls.py
```

The database-trigger command is documented in [LOCAL_DEVELOPMENT.md](docs/runbooks/LOCAL_DEVELOPMENT.md).

## Documentation

- [Implementation report](docs/implementation/FOUNDATION_DATA_HUB_IMPLEMENTATION.md)
- [Phase 2A investment implementation](docs/implementation/INVESTMENT_NATIVE_MIGRATION.md)
- [Investment assumptions and blueprint differences](docs/implementation/INVESTMENT_NATIVE_MIGRATION_ASSUMPTIONS.md)
- [Assumptions and blueprint differences](docs/implementation/FOUNDATION_DATA_HUB_ASSUMPTIONS.md)
- [Migration reconciliation](docs/implementation/MIGRATION_RECONCILIATION.md)
- [Local development runbook](docs/runbooks/LOCAL_DEVELOPMENT.md)
- [Upload/job troubleshooting](docs/runbooks/UPLOAD_AND_JOB_TROUBLESHOOTING.md)
- [Investment runs and recovery](docs/runbooks/INVESTMENT_RUNS_AND_RECOVERY.md)
- [Data access and audit](docs/security/DATA_ACCESS_AND_AUDIT.md)
- [Investment authorization and separation of duties](docs/security/INVESTMENT_AUTHORIZATION_AND_SOD.md)
- [Architecture decisions](docs/adr/ADR-001-platform-positioning.md)

The unmodified source blueprint is retained at `docs/architecture/blueprint-v0.1/`.
