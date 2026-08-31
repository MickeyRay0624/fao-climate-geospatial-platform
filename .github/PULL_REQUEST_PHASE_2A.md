## Scope

Migrate Investment & Extension Prioritisation from the preserved legacy write path to governed `investment.*` authority, exact locked inputs, immutable method/scenario versions, durable Celery analysis, catalogued outputs/lineage and native React/API workflows.

## Migrations

- Alembic `20260831_0003_investment_native_domain`
- Forward-only/restore-based rollback; no destructive downgrade
- Idempotent legacy command: `python -m app.investment.backfill_legacy --verify --materialise-outputs`

## Data reconciliation

- Legacy unchanged: 111 areas, 777 indicator values, 13 runs, 1,443 results
- Native historical copy: 13 runs, 1,443 exact results, 13 output versions, 39 assets
- Backfill second execution: zero duplicate records
- Original 54,213-byte source and SHA-256 `c30bb60f2f45ae9374578e25760a46f00257f45766bf5640c67d1cd23a34df9b` unchanged
- Regression sentinel: Prey Veng Demo Commune 03, rank 1, score 65.32

## Security

- New writes only to `investment.*`; legacy analysis POST is stable 410
- Exact input authorization and strictest-classification propagation
- Independent method/scenario editor and approver roles; creator self-approval denied
- Locked/approved/successful evidence protected by API checks and PostgreSQL triggers
- Short-lived audited downloads; object keys and signed queries omitted from logs/API evidence

## Test evidence

- Backend: 42 passed
- Frontend: 8 passed; TypeScript passed; production build passed
- npm audit: 0 vulnerabilities
- Current DB, clean DB and restored pre-change dump upgrades/backfill verified
- Live separate-layer Celery run: 111 results, checksum `741279cd97aed25f568c4dd8fc02cda6877acf3f65efe922af5d361db1841f54`
- Negative controls: idempotency conflict, cancellation, failure/retry, immutability, self-approval, unauthorized asset access, comparison creates no run

## Browser QA

All seven native module pages were inspected in the local browser. Navigation was corrected to absolute module paths. Page traversal did not create a run (count remained 14). Run Detail showed the fixed top result, 111-row worklist, map/contributions, three checksum-labelled signed assets, frozen snapshots, lineage and audit.

## Remaining non-goals

Production FAO SSO, approved production scanner, cloud deployment, raster/COG/STAC, GeoParquet/PDF exports, Extension Field Support, production telemetry/SIEM, formal method endorsement, agronomic or funding advice.

All Cambodia data, methods and scenarios remain synthetic/illustrative and non-operational.
