# ADR-009: Investment method and scenario versioning

- Status: Accepted
- Date: 2026-08-31

## Context

The synthetic MVP stored scenario choices but did not govern the formula and parameter versions as immutable, independently approved records.

## Decision

Keep logical methods in `investment.method_definitions` and immutable implementations in `investment.method_versions`. A scenario is itself a versioned record bound to one method version; its canonical parameter document is also materialised into `scenario_parameters` for auditability. Drafts may be edited, then submitted and approved by distinct principals. The database rejects edits to approved records.

Phase 2A freezes the existing weighted-linear-combination implementation and four illustrative scenarios exactly. This is governance migration, not business or agronomic validation. The scoring checksum, scenario checksum, code reference and execution metadata are captured by every run.

## Consequences

- Reproduction does not depend on mutable application defaults.
- Creator/approver separation is explicit and testable.
- A future methodology change requires a new version and cannot silently change historical results.
