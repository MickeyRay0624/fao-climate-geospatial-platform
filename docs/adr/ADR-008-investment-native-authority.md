# ADR-008: Native investment write authority

- Status: Accepted
- Date: 2026-08-31

## Context

The legacy `public.analysis_runs` and `public.priority_results` contain 13 historical runs and 1,443 results. Continuing to write them while introducing a governed domain would create two authorities and ambiguous lineage.

## Decision

All new analysis commands write only to `investment.*`. The legacy tables remain read-only evidence and their historical rows are copied, never moved, to deterministic native UUIDs. `POST /api/analysis/run` returns `410 LEGACY_ANALYSIS_READ_ONLY`; existing legacy reads remain available during the strangler period. Database triggers protect locked inputs, approved governance records, successful runs and results from mutation.

The migration has a forward-only schema upgrade. Operational rollback is restore-based from the paired PostgreSQL and object-store snapshot; downgrade does not delete governed evidence.

## Consequences

- New runs and results have one authoritative write model.
- Existing integrations can migrate from stable legacy reads without a flag day.
- Reconciliation is exact and repeatable, while removal of legacy reads is a later, separately reviewed change.
