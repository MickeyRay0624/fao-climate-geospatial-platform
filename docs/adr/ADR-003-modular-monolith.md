# ADR-003: Modular monolith

- Status: Accepted
- Date: 2026-08-31

## Context

Phase 1 needs shared transactional rules across identity, catalog, review, audit, jobs, and the legacy application. The team operates one small local Compose deployment. Microservices, Kubernetes, Kafka, and microfrontends would multiply deployment and consistency failure modes without a demonstrated scaling boundary.

## Decision

Use a FastAPI modular monolith with explicit domain modules and namespaced PostgreSQL schemas. Use a single React application shell with route-level lazy module isolation. Run background work as a separate Celery process, but share the same code and authoritative database model. Version public APIs and module manifests so later extraction remains possible.

## Consequences

- Cross-domain lifecycle/audit changes remain transactional and locally operable.
- One Compose command starts the platform.
- Code boundaries and schemas must be reviewed to prevent accidental coupling.
- A service may be extracted only after ownership, load, security, or availability evidence justifies it.
