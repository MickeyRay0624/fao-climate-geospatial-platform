# Backup and restore runbook

This procedure protects PostgreSQL and inventories MinIO before migrations. It does not delete or overwrite the active environment.

## Safety rules

- Never run `docker compose down -v`.
- Never restore over the active `rice_dss` database as a first test.
- Keep database dumps, object inventories, and `.env` outside Git; `backups/` is ignored.
- A database dump is not a complete backup without the matching MinIO inventory/objects.
- Confirm exact database and bucket targets before any restore.

## Create a snapshot

Choose a unique UTC-stamped folder, then capture database and object evidence:

```bash
snapshot_dir="backups/pre-change-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$snapshot_dir"
docker compose exec -T db pg_dump -U rice_dss -d rice_dss -Fc \
  > "$snapshot_dir/postgres.dump"
docker compose config --no-interpolate > "$snapshot_dir/compose-config-no-interpolate.yaml"
curl -fsS http://localhost:8000/health > "$snapshot_dir/health.json"
```

Do not use interpolated `docker compose config` output for an artifact because it may contain local credentials.

Capture table counts:

```bash
docker compose exec -T db psql -U rice_dss -d rice_dss -P pager=off -c \
  "SELECT 'admin_areas', count(*) FROM admin_areas
   UNION ALL SELECT 'indicator_values', count(*) FROM indicator_values
   UNION ALL SELECT 'datasets', count(*) FROM datasets
   UNION ALL SELECT 'analysis_runs', count(*) FROM analysis_runs
   UNION ALL SELECT 'priority_results', count(*) FROM priority_results;"
```

Capture an object inventory with an approved S3/MinIO client, including bucket, key, size, etag, last-modified time, and—where recorded by the platform—SHA-256. The critical legacy source must remain:

```text
datasets/1/versions/1/cambodia-rice-priority-synthetic-v1.geojson
size: 54213
sha256: c30bb60f2f45ae9374578e25760a46f00257f45766bf5640c67d1cd23a34df9b
```

Verify files are non-empty and restrict filesystem access to the snapshot folder.

## Non-destructive restore verification

Create an exact, separately named database and restore into it:

```bash
docker compose exec -T db createdb -U rice_dss rice_dss_restore_verify
docker compose exec -T db pg_restore -U rice_dss -d rice_dss_restore_verify \
  --clean --if-exists --no-owner < "$snapshot_dir/postgres.dump"
docker compose exec -T db psql -U rice_dss -d rice_dss_restore_verify -P pager=off -c \
  "SELECT (SELECT count(*) FROM admin_areas) AS areas,
          (SELECT count(*) FROM indicator_values) AS indicators,
          (SELECT count(*) FROM analysis_runs) AS runs,
          (SELECT count(*) FROM priority_results) AS results;"
```

Compare counts, catalog/version state, source key/size/SHA-256, and a known ranking. Only after verification, remove that exact temporary database:

```bash
docker compose exec -T db dropdb -U rice_dss rice_dss_restore_verify
```

The 2026-08-31 baseline was verified this way: 111 areas, 777 indicators, 13 runs, and 1,443 priority results.

## Incident rollback

1. Stop API, worker, migrate, and seed writers; leave database/object services intact.
2. Capture a fresh incident dump and object inventory before changing anything.
3. Verify the chosen recovery snapshot in a separate database as above.
4. Decide the recovery point jointly with the data owner; database and object-store time must align.
5. Restore to a new database/bucket or controlled replacement target, never by improvising over the only copy.
6. Reconfigure the application to the verified target, run read-only reconciliation, then reopen writes.

Alembic downgrade does not replace this procedure. The Phase 1 migration deliberately refuses destructive downgrade so that backfilled mappings, audit, and governance records cannot disappear silently.

## MinIO recovery note

The current baseline contains an inventory, not an independent byte-for-byte copy of the MinIO volume. For production, configure versioned object storage plus replicated/off-host backup and test object restoration. Local volume survival alone is not a backup strategy.
