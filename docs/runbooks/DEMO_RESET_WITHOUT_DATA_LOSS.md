# Reset the demonstration without data loss

## Principle

A reset must not delete the active PostgreSQL, MinIO or Redis volumes and must not overwrite the only copy of source or governed evidence. Prefer a read-only tour. If a pristine presentation state is required, restore a verified paired snapshot into a **new database** while retaining the original database and object-store volume.

Never run `docker compose down -v`, `docker volume rm`, a recursive object deletion, or restore over the active `rice_dss` database.

## 1. Capture the current state

Follow [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md) to create a fresh database dump, non-interpolated Compose evidence, legacy counts, source checksum evidence and MinIO inventory. Record the snapshot directory and verify every required file is non-empty.

Stopping application writers is safe and preserves volumes:

```bash
docker compose stop api worker
```

## 2. Choose the verified baseline

The local Phase 3 recovery point is under the ignored `backups/pre-demo-platform-20260901T072023Z/` directory. It includes the database dump and evidence that the two real-source samples existed in the matching MinIO volume. This folder is local evidence, not a portable/off-host backup.

Confirm the selected dump and inventory before continuing. If the matching source objects are not present in MinIO, stop; a database-only restore is incomplete.

## 3. Restore to a new exact database

Use a unique, narrow name. The following creates a second database and does not alter `rice_dss`:

```bash
demo_reset_db="rice_dss_demo_reset_$(date -u +%Y%m%d%H%M%S)"
docker compose exec -T db createdb -U rice_dss "$demo_reset_db"
docker compose exec -T db pg_restore -U rice_dss -d "$demo_reset_db" \
  --no-owner --exit-on-error < backups/pre-demo-platform-20260901T072023Z/postgres.dump
```

Do not use `--clean` against an active or ambiguously named database.

Upgrade and seed only the new database:

```bash
demo_reset_url="postgresql+psycopg://rice_dss:rice_demo_change_me@db:5432/$demo_reset_db"
docker compose run --rm -e DATABASE_URL="$demo_reset_url" migrate alembic upgrade head
docker compose run --rm -e DATABASE_URL="$demo_reset_url" seed
docker compose run --rm -e DATABASE_URL="$demo_reset_url" seed
```

Use the actual local password when it differs. Do not commit it.

## 4. Verify before switching

```bash
docker compose exec -T db psql -U rice_dss -d "$demo_reset_db" -P pager=off -c \
  "SELECT (SELECT count(*) FROM admin_areas) AS areas,
          (SELECT count(*) FROM indicator_values) AS indicators,
          (SELECT count(*) FROM analysis_runs) AS runs,
          (SELECT count(*) FROM priority_results) AS results;"
docker compose exec -T db psql -U rice_dss -d "$demo_reset_db" -c \
  "SELECT version_num FROM alembic_version;"
```

Expected preserved legacy baseline: 111 areas, 777 indicators, 13 runs and 1,443 results. Expected migration head: `20260901_0005`. Verify the source key, size and SHA-256 listed in the backup runbook, then confirm the real GAUL/MPI catalogue versions still resolve to existing objects.

## 5. Point the local app at the reset database

Keep the same MinIO bucket so the restored catalogue references its matching source objects. From the same shell where `demo_reset_db` is defined:

```bash
POSTGRES_DB="$demo_reset_db" docker compose up -d --force-recreate api worker web
python3 scripts/demo_smoke.py
```

Compose may briefly recreate the database service configuration, but the named volume and original database remain intact. Do not change `OBJECT_STORE_BUCKET` unless a complete paired object copy was created and verified.

## 6. Return to the original state

```bash
POSTGRES_DB=rice_dss docker compose up -d --force-recreate api worker web
python3 scripts/demo_smoke.py
```

Keep the reset database until the presentation and recovery checks are complete. Removing a temporary database is a separate destructive operation: resolve its exact name, verify the application is not using it, take a final snapshot if needed, and obtain the appropriate operator decision first.

## Lightweight refresh

When no governed records were changed, a full restore is unnecessary:

```bash
docker compose run --rm migrate
docker compose run --rm seed
docker compose run --rm --no-deps api \
  python -m app.investment.backfill_legacy --verify --materialise-outputs
docker compose restart api worker web
python3 scripts/demo_smoke.py
```

Migration, seed and backfill are idempotent. They verify/add deterministic baseline records; they do not erase deliberate case changes or newly created analysis runs.
