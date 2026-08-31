# ADR-001: Platform positioning

- Status: Accepted
- Date: 2026-08-31

## Context

The working product is a Cambodia commune rice-resilience prioritisation demonstrator with synthetic data. The blueprint introduces reusable catalog, governance, and application capabilities, but the repository does not contain real-time IoT/weather/remote-sensing ingestion, crop/water simulation, field cases, or an operational agronomic model. Calling it a digital twin would overstate evidence and scope.

## Decision

Name the product **FAO Climate Geospatial Data & Decision Platform**. Present the existing workflow as the legacy-compatible **Investment & Extension Prioritisation** application module. Preserve conspicuous synthetic, illustrative, not-operational disclaimers. Register Extension Officer Field Support as installed/disabled metadata only; provide no fake workflow or generated advice.

## Consequences

- Shared platform capabilities can grow without rewriting the working demonstrator.
- Product language accurately separates implemented evidence from roadmap.
- A future operational claim requires separately governed data/method validation, not a UI rename.
