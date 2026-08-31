# ADR-002: Single authoritative catalog

- Status: Accepted
- Date: 2026-08-31

## Context

The legacy `data_catalog_items`, `data_versions`, and `data_quality_checks` contain the published synthetic bundle. Maintaining old and new catalogs as dual-write authorities would create drift, while dropping legacy tables would destroy rollback evidence and destabilise the existing investment API.

## Decision

Backfill legacy records deterministically into `catalog.*`, retain old tables read-only as migration evidence, and send every new dataset/version/asset/quality/review write only to the new catalog. Store deterministic UUID5 mappings in `integration.legacy_id_mappings`. Compatibility endpoints adapt the new catalog to old response shapes. Keep `admin_areas`, `indicator_values`, `analysis_runs`, and `priority_results` as the investment read model until the next migration.

## Consequences

- New metadata has one source of truth.
- Existing source object and analyses remain reproducible.
- Compatibility code is temporary but explicit.
- Retirement of legacy tables requires a later, independently reconciled migration.
