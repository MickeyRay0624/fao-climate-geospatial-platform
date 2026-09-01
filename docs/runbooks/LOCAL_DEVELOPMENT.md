# Local development runbook

## Prerequisites

- Docker Desktop and Docker Compose v2
- Node.js/npm only when running frontend checks on the host
- Ports 3001, 5432, 6379, 8000, 9000, and 9001 available on loopback

All published ports bind to `127.0.0.1`; the Compose configuration is not a public deployment.

## First start

```bash
cd "/Users/lei/Documents/联合国工作/数字孪生/cambodia-rice-dss"
cp .env.example .env
docker compose config
docker compose up --build -d
docker compose ps -a
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:3001/
```

The one-command path starts PostgreSQL/PostGIS, MinIO, and Redis; runs Alembic; runs the idempotent seed; then starts FastAPI, Celery, and Vite. `migrate` and `seed` should finish with exit code 0; they are one-shot containers, not unhealthy services.

Expected health in the default development configuration is `healthy_with_warnings`, with database, object storage, Redis, and worker available and warnings for `auth_mode=dev` and `scanner=development_bypass`.

## Common commands

```bash
make logs
make migrate
make seed
docker compose restart api worker web
docker compose down
```

Never use `docker compose down -v`. It removes persistent data volumes.

## Personas and API calls

The UI banner switches between seeded local subjects. A direct request can use:

```bash
curl -fsS -H 'X-Dev-User-Subject: dev-contributor' http://localhost:8000/api/me
curl -fsS -H 'X-Dev-User-Subject: dev-reviewer' http://localhost:8000/api/me/capabilities
```

This header is development-only. Do not use it to simulate production SSO.

## Tests

```bash
docker compose run --rm --no-deps api python -m pytest -q
npm --prefix web test
npm --prefix web run build
npm --prefix web audit
python scripts/e2e_datahub.py
python scripts/e2e_negative_controls.py
```

Database trigger verification:

```bash
docker compose exec -T db psql -U rice_dss -d rice_dss -v ON_ERROR_STOP=1 \
  < scripts/verify_database_guards.sql
```

The E2E scripts expect the Compose stack on localhost and intentionally retain or archive durable test evidence instead of deleting source objects.

## Migrations

Inspect current state and re-run the idempotent upgrade:

```bash
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic upgrade head
```

The current head is `20260831_0003`. Downgrade is intentionally prohibited; follow the restore runbook for rollback.

Verify the repeatable Phase 2A backfill and exact reconciliation:

```bash
docker compose run --rm --no-deps api \
  python -m app.investment.backfill_legacy --verify --materialise-outputs
```

The Celery worker must consume both `celery` and `geospatial-analysis`. Inspect queues with:

```bash
docker compose exec -T worker celery -A app.jobs.celery_app inspect active_queues
```

## Optional GeoServer

```bash
docker compose --profile geoserver up -d geoserver
```

Open <http://localhost:8080/geoserver>. From GeoServer, the PostGIS host is `db`, port `5432`, database/user from `.env`, and the legacy schema is `public`. GeoServer is optional and not part of validation or ranking.

## Clean database bootstrap test

Do not repurpose or delete the main database. Create a named temporary database, point a one-off migration container at it, verify it, then drop only that exact database:

```bash
docker compose exec -T db createdb -U rice_dss rice_dss_clean_verify
docker compose run --rm \
  -e DATABASE_URL=postgresql+psycopg://rice_dss:rice_demo_change_me@db:5432/rice_dss_clean_verify \
  migrate alembic upgrade head
docker compose exec -T db psql -U rice_dss -d rice_dss_clean_verify -c \
  "SELECT version_num FROM alembic_version"
docker compose exec -T db dropdb -U rice_dss rice_dss_clean_verify
```

Use the actual local password when it differs; do not commit it.

## Troubleshooting startup

```bash
docker compose ps -a
docker compose logs --tail=200 migrate seed api worker web
```

- `migrate` failure: stop; do not run seed manually until the migration error is understood.
- Worker absent in health: wait one health interval, then inspect worker/Redis logs.
- Browser upload cannot reach MinIO: confirm `OBJECT_STORE_PUBLIC_ENDPOINT=localhost:9000`, while the internal endpoint remains `minio:9000`.
- Web reports a missing dependency after changing `package-lock.json`: rebuild the image. For an existing development-only node_modules volume, `docker compose exec -T web npm install` refreshes it without touching data services.
