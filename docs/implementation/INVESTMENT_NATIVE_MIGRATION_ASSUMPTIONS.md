# Investment native migration assumptions

Captured: 2026-08-31

## Facts resolved from the running system

- The pre-change database was already at Alembic `20260831_0002`; Foundation/Data Hub was committed at `71c4bd152b68359a7c84824ab673ec089f60b547` and no Git remote existed.
- The legacy source is one 54,213-byte GeoJSON object at `datasets/1/versions/1/cambodia-rice-priority-synthetic-v1.geojson`, SHA-256 `c30bb60f2f45ae9374578e25760a46f00257f45766bf5640c67d1cd23a34df9b`.
- Legacy evidence contains 111 areas, 777 indicator values, 13 runs and 1,443 priority results. It remains read-only.
- The blueprint's investment tables were placeholders in the shared SQLAlchemy metadata but had not been migrated or used as a write model.

## Decisions where the blueprint and increment differ

- Method logical identity and immutable versions are separate tables; scenarios remain versioned rows with a parameter child table. This meets the version semantics while avoiding duplicate scenario-definition terminology.
- Phase 2A produces PostGIS results plus CSV, GeoJSON and a JSON run manifest. It does not claim GeoParquet or PDF.
- The original combined bundle is retained as a compatibility input. The same bytes are also deterministically projected into one boundary and seven indicator representations so the separate-layer contract can be executed without inventing data.
- Existing public legacy GET contracts remain during the strangler phase. The legacy analysis POST is a stable `410`; no feature flag permits dual writes.
- PostgreSQL triggers provide database-level immutability. The application still performs authorization, lifecycle and optimistic-version checks first.
- The in-process metrics endpoint is Prometheus-compatible but not a production telemetry stack.

## Unknown historical fields

Legacy runs did not record every modern field. Backfill labels absent code/image/build identity as `unknown/not_recorded` in snapshots rather than fabricating it. New runs capture configured code reference, image reference/digest and build identifier when supplied.

## Product boundary

The Cambodia records, method and scenarios are synthetic and illustrative. Native governance makes execution reproducible; it does not constitute FAO endorsement, operational validation, agronomic advice or a funding recommendation.
