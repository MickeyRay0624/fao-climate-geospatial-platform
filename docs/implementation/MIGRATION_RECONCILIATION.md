# Migration reconciliation

Captured: 2026-08-31
Baseline backup: `backups/pre-platform-refactor-20260831T032524Z/` (intentionally Git-ignored)

The baseline was captured before schema migration. The PostgreSQL custom-format dump was restored into a temporary database and independently counted before that temporary database was removed. The existing database and separate clean databases upgraded to Alembic head `20260831_0002`; repeating the upgrade made no changes.

## Preservation ledger

| Metric | Before | After | Status | Notes |
|---|---:|---:|---|---|
| legacy indicator-source `datasets` | 7 | 7 | PASS | Preserved as investment read model. |
| legacy catalog datasets (`data_catalog_items`) | 1 | 1 | PASS | Retained for rollback evidence; no new Data Hub writes. |
| legacy versions (`data_versions`) | 1 | 1 | PASS | Synthetic `1.0.0` remains published/current. |
| new catalog datasets | 0 | 9 | PASS | 1 deterministic legacy backfill, 2 active successful E2E resources, and 6 archived regression resources. |
| new catalog versions | 0 | 8 | PASS | 3 published, 1 historical deprecated artifact, and 4 archived versions. |
| registered new catalog assets | 0 | 7 | PASS | Unchanged legacy source reference plus six successful regression assets. |
| MinIO objects | 1 | 8 | PASS | Original retained; six catalog regression copies and one failed/quarantine object retained. No baseline or registered catalog object was deleted; successful transient quarantine objects were removed after promotion. |
| admin areas | 111 | 111 | PASS | Geometry and indicator read model unchanged. |
| indicator rows | 777 | 777 | PASS | Seven indicators × 111 areas. |
| analysis runs | 13 | 13 | PASS | UI preview no longer persists a run. |
| priority results | 1,443 | 1,443 | PASS | Historical outputs unchanged. |
| synthetic source size | 54,213 bytes | 54,213 bytes | PASS | Original key unchanged. |
| synthetic source SHA-256 | `c30bb60f2f45ae9374578e25760a46f00257f45766bf5640c67d1cd23a34df9b` | same | PASS | Recorded in baseline and `catalog.assets`. |
| selected regression rank | 1 | 1 | PASS | Latest historical run; no new run created by preview. |
| selected regression result | Prey Veng Demo Commune 03 / 65.32 | same | PASS | Exact score comparison. |

The original MinIO key remains:

```text
datasets/1/versions/1/cambodia-rice-priority-synthetic-v1.geojson
```

## Backfill mapping

| Legacy source | New representation | Migration behavior |
|---|---|---|
| `data_catalog_items` | `catalog.datasets` | Deterministic UUID5, synthetic/not-operational metadata. |
| `data_versions` | `catalog.dataset_versions`, `catalog.assets` | Published/current state and original key/checksum/size retained. |
| `data_quality_checks` | `catalog.quality_runs`, `catalog.quality_issues` | One legacy quality run with stable structured evidence. |
| Legacy integer identifiers | `integration.legacy_id_mappings` | Entity type + old ID + deterministic UUID, idempotently seeded. |
| `admin_areas`, `indicator_values` | Existing public tables | Preserved; catalog UUID references added without rewriting values. |
| `analysis_runs`, `priority_results` | Existing public tables | Preserved unchanged for next-phase migration. |

## Restore proof

The baseline dump restored successfully into `rice_dss_restore_verify`. Counts were exactly 111 areas, 777 indicators, 7 indicator-source datasets, 1 legacy catalog record, and 13 runs. The verification database was then dropped; the backup remains untouched.

## Test artifacts

Failed and negative-control resources are deliberately lifecycle-archived, not deleted; two successful end-to-end resources remain active as repeatable demonstration evidence. They explain why the after-state contains additional catalog rows and objects. They do not change legacy counts or the active synthetic source. Their audit trails provide evidence for missing-object failure, retry restrictions, separation of duties, grant allow/deny precedence, publish immutability, deprecation, and archive behavior. One deprecated artifact predates the hardened archive transition and remains retained as historical evidence; current archive behavior transitions every non-published version to `ARCHIVED` and refuses a dataset that still contains `PUBLISHED` content.

## Rollback position

The Alembic downgrade aborts intentionally because backfill and governance/audit history must not be silently discarded. Rollback means stopping application writes, preserving a fresh incident snapshot, and restoring the verified pre-migration PostgreSQL dump together with the matching MinIO inventory. See `docs/runbooks/BACKUP_AND_RESTORE.md`.

## Phase 2A investment native migration

- Captured: 2026-08-31
- Baseline: `backups/pre-investment-native-migration-20260831T081639Z/` (Git-ignored)
- Upgrade: `20260831_0002` → `20260831_0003`

| Metric | Before | After verification | Status |
|---|---:|---:|---|
| legacy areas | 111 | 111 | PASS |
| legacy indicator values | 777 | 777 | PASS |
| legacy runs | 13 | 13 | PASS |
| legacy results | 1,443 | 1,443 | PASS |
| migrated native runs | 0 | 13 | PASS |
| migrated native results | 0 | 1,443 | PASS |
| migrated output versions | 0 | 13 | PASS |
| migrated output assets | 0 | 39 | PASS |
| native input sets | 0 | 2 locked | PASS |
| source object size | 54,213 | 54,213 | PASS |
| source SHA-256 | `c30bb60…34df9b` | same | PASS |
| fixed rank 1 | Prey Veng Demo Commune 03 / 65.32 | exact | PASS |

The historical command maps legacy run/result IDs to stable UUID5 IDs, copies values and geometry exactly, records `unknown/not_recorded` for unavailable execution metadata, and registers deterministic assets. First current/restored-dump execution created 13/1,443/39; the second created zero. Row-level verification compares IDs, scores, ranks, eligibility, bands, contributions, values and source checksum.

Clean bootstrap to `20260831_0003`, seed and backfill also passed with zero historical runs, proving the migration does not assume legacy rows exist. A restored pre-change dump upgraded and reconciled independently before its exact temporary database was removed.

One explicit live separate-layer E2E run was then retained as governed evidence. Therefore the current development database contains 14 native runs, 1,554 native results, 14 output versions, 42 associated output assets and 35 analysis-lineage edges. These extra 111 results are not legacy reconciliation rows and do not alter any legacy count.
