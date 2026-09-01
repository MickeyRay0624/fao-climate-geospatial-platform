# FAO Climate Geospatial Data & Decision Platform

This public repository is a runnable local demonstration platform: a shared application shell, governed geospatial Data Hub, native Investment Prioritisation, and a manual Extension Officer Field Support workflow for the preserved Cambodia rice-resilience demonstration.

The investment results are **synthetic demonstration data** for 111 illustrative communes. Two separately catalogued samples derived from real external sources demonstrate native boundary and indicator contracts, but their source licences remain unconfirmed and they are not operational inputs. Nothing in this repository is an official boundary, field observation, operational advice, field-scale digital twin, or endorsed FAO methodology.

## Implemented in this increment

- Responsive React application shell with capability-driven navigation, development-persona switcher, jobs, reviews, governance, audit, and help views.
- OIDC-ready identity boundary plus an explicitly labelled local development provider.
- Organizations, workspaces, memberships, groups, roles, permissions, resource grants, module registry, and workspace module enablement.
- Backend RBAC/ABAC authorization with ownership, review assignment, visibility/classification rules, and explicit `DENY` precedence.
- Versioned Data Hub APIs and the governed lifecycle from private draft through direct upload, background validation, review, immutable publication, sharing, preview/download, lineage, deprecation, and archive.
- Validation profiles for the legacy analysis bundle, generic GeoJSON, CSV tables, and basic documents.
- Celery/Redis jobs with durable PostgreSQL state, progress steps, retry rules, idempotency, and audit events.
- Alembic schemas for `iam`, `core`, `governance`, `catalog`, `jobs`, `audit`, `integration`, `investment`, and `extension`.
- Strangler backfill of the existing catalog into the new authoritative `catalog.*` model without moving or modifying the original MinIO object.
- Locked exact-version input sets for both the legacy bundle and separate boundary plus seven indicator layers.
- Immutable method/scenario versions with separate editor and approver roles.
- Explicit Celery analysis runs with durable state, cancellation/failure evidence, deterministic results and idempotency.
- Native run history/detail, maps, contributions, comparison, audit, signed outputs and catalog lineage.
- Historical backfill of 13 legacy runs and 1,443 results with deterministic UUID mappings and exact row reconciliation.
- Mobile-first Extension worklists, assigned-case access, observations, restricted media, manual assessments, verification, activities, follow-ups, supervision, knowledge approval, and offline-draft sync status.
- Governance views for memberships, groups, roles, data policy, quality profiles, knowledge approval, applications, retention, audit filtering/CSV export, and system health.
- Controlled single-layer Shapefile ZIP and GeoPackage validation with archive safety controls, source preservation, derived WGS84 GeoJSON previews, checksums, downloads, and lineage.
- Nested help and demonstration-guide routes, deterministic seed data, responsive/PWA behavior, and a non-destructive reset runbook.

Not implemented: production FAO SSO connection, an approved production malware scanner, cloud deployment, raster/COG/STAC processing ([issue #5](https://github.com/MickeyRay0624/fao-climate-geospatial-platform/issues/5)), full PostGIS materialisation and multi-layer vector selection ([issue #4](https://github.com/MickeyRay0624/fao-climate-geospatial-platform/issues/4)), GeoParquet/PDF investment exports, business endorsement of the method, or automated/agronomic advice.

The source repository is public. The running application remains a loopback-only local demonstration and is not a public or production service.

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
- Extension module: <http://localhost:3001/apps/extension-field-support/worklist>
- Governance health: <http://localhost:3001/governance/system-health>
- Demonstration guide: <http://localhost:3001/help/demo-guide>
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
| `dev-extension-officer-1` | Sreypov Mom | extension officer with assigned cases |
| `dev-extension-officer-2` | Rithy Touch | second extension officer |
| `dev-extension-supervisor` | Sokha Meas | extension supervisor |
| `dev-knowledge-editor` | Pisey Heng | knowledge version editor |
| `dev-knowledge-approver` | Kunthea Sim | independent knowledge approver |

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
- `generic-vector@1.0`: non-empty GeoJSON, or one controlled WGS84 Shapefile ZIP/GeoPackage layer, with geometry/schema summary and derived GeoJSON preview;
- `generic-table@1.0`: parseable CSV with header/row/schema sampling;
- `document@1.0`: PDF, DOCX, Markdown, and text cataloging without OCR or content exposure.

Direct uploads use short-lived presigned URLs. In local development the scanner is an explicit `development scan bypass`; the health endpoint returns `healthy_with_warnings`. Staging and production cannot enable this bypass.

## Migrations and seed

```bash
make migrate
make seed
```

Alembic supports an existing legacy database and clean bootstrap. Head `20260901_0005` adds the Extension Field Support domain after the Data Hub collection and native investment revisions. Destructive downgrade is intentionally blocked and recovery uses paired database/object snapshots. Seed and investment backfill are idempotent and never overwrite a differing source object.

Run or re-verify the native historical migration:

```bash
docker compose run --rm --no-deps api \
  python -m app.investment.backfill_legacy --verify --materialise-outputs
```

## Verification

```bash
docker compose run --rm --no-deps api python -m pytest -q
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web audit --audit-level=high
python scripts/check_contracts.py
python scripts/e2e_datahub.py
python scripts/e2e_negative_controls.py
python scripts/e2e_investment.py
python scripts/demo_smoke.py
npm --prefix web run test:e2e
```

The database-trigger command is documented in [LOCAL_DEVELOPMENT.md](docs/runbooks/LOCAL_DEVELOPMENT.md).

## Documentation

- [Implementation report](docs/implementation/FOUNDATION_DATA_HUB_IMPLEMENTATION.md)
- [Phase 2A investment implementation](docs/implementation/INVESTMENT_NATIVE_MIGRATION.md)
- [Platform architecture overview](docs/architecture/PLATFORM_OVERVIEW.md)
- [Extension domain architecture](docs/architecture/EXTENSION_DOMAIN.md)
- [Demonstration guide](docs/demo/DEMO_GUIDE.md)
- [Non-destructive demonstration reset](docs/runbooks/DEMO_RESET_WITHOUT_DATA_LOSS.md)
- [v0.3.0 demonstration release notes](docs/releases/v0.3.0-demo-platform.md)
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
