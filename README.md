# FAO Climate Geospatial Data & Decision Platform

This repository is the first runnable platform increment: a shared application shell, governed geospatial Data Hub, and the existing Cambodia rice-resilience DSS preserved as the first application module.

The current Cambodia data are **synthetic demonstration data** for 111 illustrative communes. They are not official boundaries, observations, operational advice, a field-scale digital twin, or an endorsed FAO methodology.

## Implemented in this increment

- Responsive React application shell with capability-driven navigation, development-persona switcher, jobs, reviews, governance, audit, and help views.
- OIDC-ready identity boundary plus an explicitly labelled local development provider.
- Organizations, workspaces, memberships, groups, roles, permissions, resource grants, module registry, and workspace module enablement.
- Backend RBAC/ABAC authorization with ownership, review assignment, visibility/classification rules, and explicit `DENY` precedence.
- Versioned Data Hub APIs and the governed lifecycle from private draft through direct upload, background validation, review, immutable publication, sharing, preview/download, lineage, deprecation, and archive.
- Validation profiles for the legacy analysis bundle, generic GeoJSON, CSV tables, and basic documents.
- Celery/Redis jobs with durable PostgreSQL state, progress steps, retry rules, idempotency, and audit events.
- Alembic schemas for `iam`, `core`, `governance`, `catalog`, `jobs`, `audit`, `integration`, and the future `investment` domain.
- Strangler backfill of the existing catalog into the new authoritative `catalog.*` model without moving or modifying the original MinIO object.
- Legacy Investment & Extension Prioritisation workflow, map, ranking, explanations, quality evidence, CSV export, and GeoJSON export under the new shell.

Not implemented: production FAO SSO connection, an approved production malware scanner, cloud/public deployment, raster/COG/STAC processing, the Extension Officer Field Support workflow, LLM or agronomic advice, or full migration of investment analysis history into the new domain.

## Local architecture

```text
Browser (React + TypeScript)
  ├─ /api ──────► FastAPI modular monolith
  │                ├─ PostgreSQL/PostGIS: authoritative metadata and read models
  │                ├─ MinIO: immutable source assets and quarantine objects
  │                └─ Redis ─► Celery worker: validation jobs
  └─ signed PUT/GET ─► MinIO (short-lived URLs; no permanent browser credentials)

Optional GeoServer ─────────► PostGIS publication layer
```

The new catalog is authoritative for all new dataset metadata. The legacy `admin_areas`, `indicator_values`, `analysis_runs`, and `priority_results` remain the investment module's read model during the strangler migration.
The legacy investment catalogue URLs remain as read adapters over the authoritative catalog and deterministic backfill mappings. Their former upload/publish mutations return `410 LEGACY_CATALOG_READ_ONLY`, preventing dual writes while preserving the existing UI contract.

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

- Platform: <http://localhost:3000/home>
- Data Hub: <http://localhost:3000/data/catalog>
- Investment module: <http://localhost:3000/apps/investment-prioritisation/overview>
- OpenAPI: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- MinIO console: <http://localhost:9001>

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

Use the banner switcher in the UI or send `X-Dev-User-Subject: <subject>` locally. The API refuses development identity headers outside `APP_ENV=development|test`; production/staging configuration fails closed. See [DEV_AUTH_AND_OIDC_BOUNDARY.md](docs/security/DEV_AUTH_AND_OIDC_BOUNDARY.md).

## Data Hub workflow

```text
create dataset → draft version → direct upload to quarantine
  → background scan/validation → quality evidence → independent review
  → publisher action → immutable published snapshot → governed access
```

Supported profiles:

- `analysis-ready-priority-bundle@1.0`: existing GeoJSON or CSV+WKT investment bundle rules;
- `generic-vector@1.0`: non-empty GeoJSON `FeatureCollection` with geometry/schema summary;
- `generic-table@1.0`: parseable CSV with header/row/schema sampling;
- `document@1.0`: PDF, DOCX, Markdown, and text cataloging without OCR or content exposure.

Direct uploads use short-lived presigned URLs. In local development the scanner is an explicit `development scan bypass`; the health endpoint returns `healthy_with_warnings`. Staging and production cannot enable this bypass.

## Migrations and seed

```bash
make migrate
make seed
```

Alembic supports both an existing legacy database and a clean database. The first revision includes non-destructive backfill; destructive downgrade is intentionally blocked and recovery uses the pre-migration backup. Seed operations are idempotent and do not overwrite user-created catalog resources.

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
- [Assumptions and blueprint differences](docs/implementation/FOUNDATION_DATA_HUB_ASSUMPTIONS.md)
- [Migration reconciliation](docs/implementation/MIGRATION_RECONCILIATION.md)
- [Local development runbook](docs/runbooks/LOCAL_DEVELOPMENT.md)
- [Upload/job troubleshooting](docs/runbooks/UPLOAD_AND_JOB_TROUBLESHOOTING.md)
- [Data access and audit](docs/security/DATA_ACCESS_AND_AUDIT.md)
- [Architecture decisions](docs/adr/ADR-001-platform-positioning.md)

The unmodified source blueprint is retained at `docs/architecture/blueprint-v0.1/`.
