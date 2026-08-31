# Investment authorization and separation of duties

## Enforcement boundary

The browser is not trusted. Every native API operation requires active development/OIDC identity, workspace membership, enabled module, declared permission and resource-level access. Run access is no broader than the strictest selected input classification. Unauthorized reads do not expose source object keys; downloads issue short-lived URLs only after a fresh authorization decision.

## Permission bundles

- Spatial analyst: create/lock input sets, create/view/cancel owned runs, export, compare and submit results for review.
- Viewer: view and compare permitted runs only.
- Method editor: edit/submit draft method and scenario versions; cannot approve.
- Method approver: approve/retire submitted versions; cannot author with the seeded role.
- Workspace administrator: platform operations and audited owner cancellation, but not a bypass of dataset access checks.

Seeded development subjects `dev-method-editor` (Chantha Ros) and `dev-method-approver` (Bopha Keo) are distinct principals and groups. They are local test identities, not FAO SSO.

## Separation rules

- A method/scenario creator cannot approve the same version.
- Approved methods/scenarios and locked input sets are immutable in both API and PostgreSQL.
- A successful run and its results cannot be rewritten; corrections create a new run.
- An analyst may submit a result dataset for review but cannot be its sole reviewer/publisher under the existing Data Hub review rules.
- Comparison is read-only and does not create an analysis run.

## Audit and safe logging

Material create, submit, approve, lock, run, cancel, fail, complete, export, compare, output-register and review-submit actions append to `audit.events`. Safe structured fields are run/workspace/method IDs, status and correlation ID. Parameters, object credentials, tokens and signed query strings are not logged. The metrics endpoint exposes counters/durations without resource payloads or sensitive identifiers.

Database triggers reject updates/deletes to audit events and immutable investment evidence. Database superusers remain outside the application security boundary; production still requires least-privilege roles, managed identity, centralized immutable audit export, TLS/ingress controls and SIEM monitoring.
