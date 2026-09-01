# Investment runs and recovery

## Normal operations

Confirm the stack and queue before creating runs:

```bash
docker compose ps -a
curl -fsS http://localhost:8000/health
docker compose exec -T worker celery -A app.jobs.celery_app inspect active_queues
```

The worker must consume `geospatial-analysis`. Open the native module at <http://localhost:3001/apps/investment-prioritisation/overview>. Opening, listing, inspecting or comparing records is read-only. Only the explicit create command starts a run.

Run state and structured job evidence are available from:

```bash
curl -fsS -H 'X-Dev-User-Subject: dev-analyst' \
  http://localhost:8000/api/apps/investment-prioritisation/v1/runs/RUN_UUID
curl -fsS -H 'X-Dev-User-Subject: dev-analyst' \
  http://localhost:8000/api/jobs/v1/jobs/JOB_UUID
```

Use a new, non-secret `Idempotency-Key` for each logical mutation. Retrying the same request with the same key returns the same resource; a different payload returns `409 IDEMPOTENCY_KEY_CONFLICT`.

## Backfill and verification

Backfill is safe to repeat:

```bash
docker compose run --rm --no-deps api \
  python -m app.investment.backfill_legacy --verify --materialise-outputs
```

Expected baseline: 13 migrated runs, 1,443 results, 13 output versions and 39 assets. A second execution reports zero created runs/results/assets. Never delete legacy rows after a successful copy; they remain rollback and reconciliation evidence.

## Cancellation

Only the owner or workspace administrator can request cancellation. It is accepted while queued or in an early running step. Once `register-output` or `finalise` starts, the API refuses cancellation because a catalog commit must be atomic. A worker converts `cancel_requested` to `cancelled`, deletes unregistered native results and retains the job/audit trail.

## Failure and retry

1. Read the run `failure`, job steps and correlation ID; do not edit the database row.
2. Inspect `docker compose logs --tail=300 worker api` and object-store health.
3. Resolve the underlying missing/corrupt input, worker or storage condition. Exact input checksum changes require a new input-set version and a new run.
4. Use the existing job retry endpoint only for a failed retryable job. It reuses the immutable run snapshots. Never requeue by changing status with SQL.
5. Verify final result/output checksums and lineage before accepting recovery.

The task cleans unregistered output keys on failure. If a deterministic key already contains different bytes, it fails closed; investigate instead of overwriting.

## Reconciliation queries

```sql
SELECT count(*) FROM public.analysis_runs;             -- 13
SELECT count(*) FROM public.priority_results;          -- 1443
SELECT count(*) FROM investment.analysis_runs
 WHERE migration_source='investment-native-phase-2a/1.0'; -- 13
SELECT count(*) FROM investment.priority_results r
 JOIN investment.analysis_runs a ON a.id=r.run_id
 WHERE a.migration_source='investment-native-phase-2a/1.0'; -- 1443
```

Use the backfill `--verify` option for row-level field/checksum reconciliation rather than relying only on counts.

## Restore-based rollback

The migration downgrade is intentionally non-destructive and is not rollback.

1. Stop API/worker/migrate/seed writers without deleting volumes.
2. Capture a fresh incident database dump and MinIO inventory.
3. Restore `backups/pre-investment-native-migration-20260831T081639Z/postgres.dump` into a separately named database and verify 111/777/13/1,443 plus the original source checksum.
4. Pair database state with the matching object-store snapshot/inventory; do not restore one side independently.
5. Point an isolated application at the restored targets and run read-only reconciliation.
6. Choose and execute the controlled cutover with the data owner. Preserve native incident evidence for investigation.

Never run `docker compose down -v`, delete `investment.*`, overwrite the legacy object, or force an Alembic downgrade.
