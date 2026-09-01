# Platform architecture overview

## Positioning

This codebase is a local, governed demonstration platform. It proves application boundaries, durable workflows and evidence handling; it is not an internet deployment, an operational decision system or a field-scale digital twin. The repository is public, while all Compose ports bind to loopback.

The architecture is a modular monolith. One React shell discovers enabled applications and effective permissions. One FastAPI service owns HTTP policy enforcement. PostgreSQL/PostGIS is authoritative for structured state, MinIO for source and derived objects, and Redis/Celery for asynchronous execution. Optional GeoServer is outside the critical path.

```text
React application shell
  |-- Data Hub ----------------------|
  |-- Investment Prioritisation -----|--> FastAPI policy + module routers
  |-- Extension Field Support -------|         |
  |-- Governance / audit / help -----|         |-- PostgreSQL/PostGIS
  |                                           |-- MinIO
  `-- short-lived signed object transfer       `-- Redis --> Celery worker
```

## Authoritative boundaries

| Concern | Authority | Important invariant |
|---|---|---|
| Identity, membership, roles and grants | `iam`, `core`, `governance` schemas | Explicit deny wins; local identity headers fail closed outside development/test. |
| Dataset lifecycle and metadata | `catalog` schema | Published versions, assets and representations are immutable. |
| Processing jobs | `jobs` schema | PostgreSQL state is authoritative; Redis only transports work. |
| Audit | `audit.events` | Append-only at API and database-trigger layers. |
| New investment runs and results | `investment` schema | Exact input, method and scenario versions are locked before formal execution. |
| Field-support workflow | `extension` schema | Assignment-scoped access, manual assessment and append-only completed evidence. |
| Binary source/derived evidence | MinIO | Source objects are preserved; derived objects have separate keys and hashes. |
| Legacy Cambodia demonstration | legacy public tables plus deterministic mappings | Existing rows and the original source object are preserved as migration evidence. |

Legacy catalogue and analysis reads remain compatibility adapters. Their former write routes return `410`, so there is no dual-write path.

## Governed flows

### Data Hub

`draft -> quarantine upload -> scan -> profile validation -> review -> approval -> publication`

The browser uploads with a short-lived signed PUT. The worker validates, records quality issues, registers representations and lineage, and moves a passing source from quarantine. A later preview or download re-evaluates access and records an audit event. In development the scanner status is visibly `BYPASSED_DEV`; staging and production configuration cannot enable that bypass.

### Investment Prioritisation

Formal execution requires a locked, ready input set, approved method version and approved scenario. New runs are native `investment.*` records; the preserved 13 legacy runs are mapped deterministically. Successful results are immutable, have a result checksum, and register a derived Data Hub output plus lineage.

The two real-source compatibility samples demonstrate native profiles only. Their deliberately incomplete input set remains not ready and cannot be run. The complete runnable example and all rankings are synthetic.

### Extension Field Support

`case -> assignment -> observation -> manual assessment -> verification -> activity -> follow-up`

The module is assignment-aware and mobile-first. Field media is classified `SENSITIVE_FIELD`, size/type bounded, stored separately and never placed in service-worker caches. Completed observations and history are database-protected. Knowledge versions and activity approvals use separate actors.

### Governance and operations

Governance views expose membership, group, role, application, policy and approval read models. Audit supports constrained filters and CSV export. System health checks database, object storage, Redis, worker heartbeat, migration head, scanner posture, queue depth and local backup evidence without returning secrets.

## Evidence labels

- `REAL_SAMPLE`: derived from a real external source for compatibility testing. Licence and operational fitness must be confirmed separately.
- `SYNTHETIC_DEMO`: deterministic illustrative content that may be run and reset locally.
- `DEMONSTRATION`: field-support records and knowledge placeholders that do not represent real people, farms, diagnosis or advice.
- `NOT_CONFIRMED`: source licence is not confirmed; do not redistribute or use operationally.

## Current limits

- Production SSO, approved malware scanning, managed secrets, TLS/ingress, least-privilege database roles, central audit export and off-host backup remain required.
- Direct vector validation supports one WGS84 Shapefile ZIP or GeoPackage layer and derives GeoJSON. Full PostGIS materialisation, layer selection and reviewed reprojection are tracked in [issue #4](https://github.com/MickeyRay0624/fao-climate-geospatial-platform/issues/4).
- GeoTIFF/COG validation and authorised raster tiles require reviewed raster dependencies, a tile policy boundary and an approved fixture; see [issue #5](https://github.com/MickeyRay0624/fao-climate-geospatial-platform/issues/5).
- No automated diagnosis, agronomic recommendation or business endorsement is provided.

The architecture decisions under `docs/adr/` define the durable choices. The unmodified source blueprint remains under `docs/architecture/blueprint-v0.1/` for traceability.
