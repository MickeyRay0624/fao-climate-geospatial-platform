# ADR-005: Provider-neutral identity and layered authorization

- Status: Accepted
- Date: 2026-08-31

## Context

The local pilot needs test personas now but must not bake development headers or passwords into a production identity design. Roles alone cannot express private ownership, reviewer assignment, data classification, explicit deny, time-bounded sharing, module enablement, or separation of duties.

## Decision

Resolve OIDC or development identity into one `Principal`; store no local password. Gate the development provider by environment and explicit configuration, failing closed outside development/test. Authorize on the backend through active identity/membership, module/entitlement, classification/visibility, deny-first resource grants, ownership/assignment, role permission, resource state, and duty separation. Do not make platform administrators implicit readers of all datasets.

## Consequences

- UI capability filtering improves usability but is never authoritative.
- FAO IdP can be connected without changing business authorization.
- More contextual tests are required than pure role checks.
- Production still needs approved claims/provisioning, access reviews, and a governed break-glass process.
