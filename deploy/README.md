# Server demo deployment

This directory contains the isolated low-traffic demonstration deployment for
`dss.lmqstudio.com`. It does not reuse the existing host MySQL, Redis, Node, or
Nginx virtual hosts.

## Runtime topology

- Host Nginx terminates TLS; the temporary Basic Auth gate is currently disabled
  for team review.
- The static React build listens on host loopback port `3011`.
- FastAPI listens on host loopback port `8011`.
- MinIO API and console listen on host loopback ports `9010` and `9011`.
- PostgreSQL and Redis have no host port.
- GeoServer is intentionally excluded from the small demo server.

The application remains in visibly labelled development-identity mode because
an approved OIDC provider is not connected. Only synthetic demonstration data
may be exposed while the ingress password gate is disabled.

## Safety

Never run `docker compose down -v`. The named PostgreSQL, MinIO, and Redis
volumes contain the deployed demonstration state.

Copy `.env.production.example` to `.env.production`, replace every secret and
deployment identifier, and keep the resulting file mode at `0600`.

Run Compose from this directory:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml up --build -d
```

## One-time demonstration data

The clean seed intentionally has no historical analysis runs. Create the
governed separate-layer inputs, then execute one deterministic demonstration
run so that the results and export screens are populated:

```bash
docker exec cambodia-rice-dss-api-1 \
  python -m app.investment.backfill_legacy --verify --materialise-outputs
docker cp ../scripts/e2e_investment.py \
  cambodia-rice-dss-api-1:/tmp/e2e_investment.py
docker exec cambodia-rice-dss-api-1 python /tmp/e2e_investment.py
```

This should produce 111 ranked results with checksum
`741279cd97aed25f568c4dd8fc02cda6877acf3f65efe922af5d361db1841f54`.

## Host ingress and DNS

The deployed host uses these public records:

- `dss.lmqstudio.com` -> `150.109.185.196`
- `storage.dss.lmqstudio.com` -> `150.109.185.196`

Install `nginx-dss.conf` as a separate host virtual server and issue a
certificate covering both names. The current team-review deployment does not
require Basic Auth. The dormant server-local file `/etc/nginx/.htpasswd-dss`
is retained only so an ingress password gate can be restored quickly. Do not
add Basic Auth to the storage hostname: browser-facing MinIO URLs are already
short-lived signatures and must remain directly downloadable.

The current server checkout is `/opt/lmqstudio/dss`; the production environment
file is `/opt/lmqstudio/dss/deploy/.env.production` and must remain mode `0600`.

## Verification and recovery point

After a deploy or restart, confirm all long-running services are healthy and
both one-shot services exited successfully:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml ps -a
curl -fsS http://127.0.0.1:8011/health
curl -fsS http://127.0.0.1:9010/minio/health/live
```

Create a coordinated PostgreSQL dump and matching MinIO-volume copy before a
material change. The first deployed recovery point is stored outside the
checkout under `/opt/lmqstudio/backups/`. It is a server-local recovery point,
not an off-host disaster-recovery copy. Follow
`docs/runbooks/BACKUP_AND_RESTORE.md` for subsequent snapshots and never restore
over the active database without verifying a separately named restore first.
