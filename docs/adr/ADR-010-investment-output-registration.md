# ADR-010: Investment output registration

- Status: Accepted
- Date: 2026-08-31

## Context

A database result table alone is insufficient evidence for reuse, download, review and exact lineage in the Data Hub.

## Decision

Each successful native run creates a deterministic derived `catalog.dataset_version`, three immutable assets (`priority-ranking.csv`, `priority-ranking.geojson`, and `run-manifest.json`) and a lineage process with exact input-version `used` edges and one generated-output edge. Assets are written under:

```text
catalog/{workspace_id}/datasets/{dataset_id}/versions/{version_id}/derived/
```

Object bytes are verified against SHA-256 before registration. A retry reuses identical bytes but refuses a conflicting object. Downloads are re-authorised, short-lived and audited. GeoParquet and PDF are not declared because Phase 2A does not generate them; the active module contract is version `2.0.0` and lists only real representations.

## Consequences

- Outputs are catalog resources with checksums and provenance, not ad-hoc downloads.
- A failed run cannot publish a partial version.
- Additional representations require implementation, checksum verification and a contract change.
