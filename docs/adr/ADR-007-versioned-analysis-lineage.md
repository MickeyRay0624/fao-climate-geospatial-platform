# ADR-007: Versioned analysis lineage

- Status: Accepted
- Date: 2026-08-31

## Context

Decision outputs are meaningful only with exact input version, method/parameters, execution identity, and derived artifacts. The current legacy analysis already records runs/results, but page initialisation formerly created a persisted run and the future platform model needs explicit catalog lineage.

## Decision

Require analysis to select a published catalog version and preserve its reference in legacy runs/read models. Use a non-persistent preview for page initialisation; persist only an explicit user run. Record Data Hub ingestion and asset relationships through `catalog.lineage_processes` and `catalog.lineage_edges`. In the next investment sprint, introduce immutable method versions and input sets, asynchronous runs, and register derived outputs back into the catalog with PROV-like used/generated edges.

## Consequences

- Navigation no longer pollutes run history.
- Existing results remain tied to the synthetic `1.0.0` source.
- Phase 1 lineage covers catalog ingestion/publication but not yet a fully migrated investment run graph.
- Future comparison/export must use stored method/input snapshots rather than mutable defaults.
