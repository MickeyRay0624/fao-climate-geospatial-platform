# Phase 2A investment native migration

- Completed: 2026-08-31
- Branch: `feat/investment-native-migration`
- Alembic head: `20260831_0003`

## Outcome

Investment Prioritisation now uses `investment.*` as its only new-run/result write authority. The preserved synthetic method runs as a deterministic Celery job from exact locked Data Hub inputs, stores immutable snapshots and PostGIS results, then registers a catalogued output version with CSV, GeoJSON, manifest checksums and full input/output lineage. The React module uses only the versioned native API for overview, creation, history, detail, inputs, comparison, methods and scenarios.

Legacy `public.analysis_runs` and `public.priority_results` are unchanged. Their 13/1,443 records were copied to deterministic native UUIDs and reconciled row by row. Repeating the backfill creates zero additional records.

## Schema and migration

Revision `20260831_0003_investment_native_domain` creates:

- `indicator_definitions`, `method_definitions`, `method_versions`;
- `scenarios`, `scenario_parameters`;
- `analysis_input_sets`, `analysis_input_members`;
- `analysis_runs`, `analysis_run_inputs`, `priority_results`, `run_comparisons`.

Foreign keys connect exact catalog versions/representations, jobs, actors and derived output versions. Check constraints, unique keys and triggers enforce state, separation, locked-input immutability, approved-governance immutability and successful-evidence immutability. The revision is safe for both the existing database and clean bootstrap. Downgrade is deliberately restore-only.

## Governed method and scenarios

`legacy-weighted-linear-combination / legacy-wlc-1.0.0` freezes the current formula: entered weights are normalised, missing indicators use neutral `0.5`, completeness applies `0.92 + 0.08 × completeness`, scores persist to two decimals, eligibility uses rice area, relative bands use 20/50/80 percent breaks and ties use score-descending then area-code-ascending. Four existing scenarios are approved immutable `1.0.0` records.

`dev-method-editor` and `dev-method-approver` have separate role bundles and group membership. A creator cannot approve their own method or scenario version. This migration preserves an illustrative technique; it does not validate or endorse it.

## Exact inputs

Two locked input sets are seeded/backfilled:

- the unchanged published legacy bundle, including its original object key and checksum;
- one administrative boundary plus seven normalised indicator layers, each a published catalog representation derived deterministically from the same source bytes.

Input validation checks required roles, profile compatibility, publication state, access, representation/object checksum, area join keys, indicator metadata, value ranges and coverage. Locking stores a canonical checksum and prevents member or business-field changes. A run copies every selected version/representation/object checksum into `analysis_run_inputs` before dispatch.

## Asynchronous lifecycle

`POST /api/apps/investment-prioritisation/v1/runs` requires an idempotency key and returns a durable queued run/job. Celery task `investment:run-prioritisation:v1` consumes `geospatial-analysis` and records six visible steps:

```text
validate-inputs → prepare → score → materialise-results → register-output → finalise
```

Run and job states are committed between steps. Cancellation is safe until output registration; a worker observes `cancel_requested`, removes unregistered results and records `cancelled`. Failures store a stable code, correlation ID and non-sensitive exception type, clean unregistered objects and leave retry evidence in the durable job. A completed retry returns the existing checksum instead of duplicating results.

## Results, catalog and lineage

Results store area identity/geometry, raw/final score, rank, band, eligibility, indicator values, contributions, missing fields, completeness and quality evidence. Each successful run registers a deterministic derived Data Hub version and exactly three verified assets:

- `priority-ranking.csv`;
- `priority-ranking.geojson`;
- `run-manifest.json`.

An `analysis` lineage process records one `used` edge per exact input version and one generated-output edge. Asset endpoints re-authorise each request, omit object keys and issue 15-minute signed URLs; access is audited. Result review submission enters the existing independent Data Hub review/publish lifecycle.

## API and UI

The versioned native API exposes overview/capabilities/data profiles; input-set CRUD, validation, lock/clone/retire; method and scenario draft/review/approve/retire; run create/list/detail/cancel/results/area/lineage/audit/assets/exports; comparisons; and metrics. Mutations use canonical request hashing and idempotency records. Unauthorized resource reads fail closed.

The UI opens without creating a run. Run creation is an explicit submit followed by polling of a read-only detail. Run History and Run Detail expose states, step progress, map, worklist, per-area contributions, checksums, lineage, audit and authorized assets. Compare computes evidence only from two immutable completed runs and never starts analysis.

## Backfill and reconciliation

Run:

```bash
docker compose run --rm --no-deps api \
  python -m app.investment.backfill_legacy --verify --materialise-outputs
```

The command publishes deterministic boundary/indicator representations, locks their input set, maps legacy integer IDs to UUID5 IDs, copies exact results and registers outputs. On the migrated baseline the first run produced 13 native runs, 1,443 results and 39 assets; the second produced zero new records. It also succeeds on clean bootstrap, where there is no historical evidence to migrate.

## Validation evidence

- Current DB, clean DB and restored `20260831_0002` dump upgraded to head and passed backfill verification; the backfill was repeated on restored/current data.
- Backend regression: 42 tests passed.
- Frontend: 8 tests passed, TypeScript check and production build passed, npm audit reported zero vulnerabilities.
- Live Celery E2E on the separate-layer input produced 111 results and output version `2d8e02d6-fc31-5117-8081-7b3d6977767d`; result checksum `741279cd97aed25f568c4dd8fc02cda6877acf3f65efe922af5d361db1841f54`.
- Browser QA covered all seven module pages, fixed an absolute-routing defect, verified no implicit run (count stayed 14), and inspected the 111-row detail, fixed sentinel, signed assets, lineage and audit evidence.
- Fixed regression remains rank 1 `Prey Veng Demo Commune 03`, score `65.32`.

Final test counts and GitHub delivery evidence are recorded in the pull request and the final handoff; they may supersede the counts above if tests are expanded before push.

## Recovery and limitations

Rollback follows [INVESTMENT_RUNS_AND_RECOVERY.md](../runbooks/INVESTMENT_RUNS_AND_RECOVERY.md) and the paired pre-change snapshot `backups/pre-investment-native-migration-20260831T081639Z/`, which is Git-ignored. No downgrade deletes native evidence.

Not implemented: production FAO SSO, approved malware scanning, cloud deployment, raster/COG/STAC processing, GeoParquet/PDF exports, production telemetry/SIEM, Extension Field Support, business validation of the method, or agronomic/LLM advice.
