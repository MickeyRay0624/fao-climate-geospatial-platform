# Demonstration guide

## Before the session

Start the stack, then run the read-only smoke check:

```bash
docker compose up --build -d
python3 scripts/demo_smoke.py
```

Open <http://localhost:3001/home>. Keep the development-persona banner visible so the audience can see which duties are active. This is a local demonstration: do not enter names, contact details, precise farm locations or real field media.

Use these labels consistently:

- **Real source sample**: derived from a real user-supplied source, licence not confirmed, compatibility evidence only.
- **Synthetic demo**: deterministic illustrative data and analysis output; safe to run locally, not an operational result.
- **Demonstration record**: fictional Extension case/knowledge content; no real farmer or farm.
- **Local control**: implemented locally but still requiring production infrastructure or organizational approval.

## Guided sequence

### 1. Platform overview

Persona: `dev-admin`. Route: <http://localhost:3001/home>.

Show the installed Data Hub, Investment and Extension applications, jobs/reviews summary, visible development-identity banner and demonstration disclaimer. State that repository visibility does not make the local application a deployed public service.

### 2. Workspace and duties

Routes: <http://localhost:3001/governance/members>, <http://localhost:3001/governance/roles>.

Show the 14 seeded personas and separation between contributor, reviewer, publisher, investment method editor/approver, extension officer/supervisor and knowledge editor/approver. Switch to `dev-viewer` briefly to demonstrate capability-driven navigation, then return to `dev-admin`.

### 3. Governed catalogue

Route: <http://localhost:3001/data/catalog>.

Point out evidence badges, classification/visibility, lifecycle state, profile, quality and licence warning. Explain that the catalog is authoritative and legacy reads are adapters only.

### 4. Real GAUL boundary preview

Persona: `dev-contributor`. In the catalogue, open **HIH Cambodia GAUL 2024 level-1 boundary compatibility test** and published version `1.1.0`; choose **Preview**, **Quality** and **Download**.

Expected: 26 features, Cambodia extent, native `administrative-boundary@1.0`, a quality warning rather than a false clean claim, source checksum, and `UNCONFIRMED-SOURCE-LICENCE`. Label it **real source sample**, not official boundary data.

### 5. Real MPI table and lineage

Open **HIH Cambodia MPI 2025 compatibility test**, version `1.1.0`; choose **Preview**, **Quality** and **Lineage**.

Expected: 26 rows, one visible missing-value warning, native `normalised-indicator-layer@1.0`, source/derived evidence and licence warning. Label it **real source sample** and do not interpret it as a complete priority model.

### 6. Data lifecycle

Use the already-published synthetic **Phase 1 workflow verification** dataset if present, or walk through the diagram at <http://localhost:3001/help/data-hub>. Show creator, review and publication evidence without creating a new record during a standard presentation.

Explain `draft -> upload -> validation -> independent review -> publication`, short-lived object URLs, immutable published versions and new-version correction. In development, file scan status is `BYPASSED DEV`, never “clean”.

### 7. Honest real-data readiness

Persona: `dev-analyst`. Route: <http://localhost:3001/apps/investment-prioritisation/readiness>.

Open **HIH real-data compatibility probe — incomplete by design**. Expected: readiness is false because only a boundary and poverty layer are present while the method requires a boundary plus seven exact indicator roles. Lock/run controls remain unavailable. No real-data ranking exists.

### 8. Synthetic run

Route: <http://localhost:3001/apps/investment-prioritisation/new-run>.

Select **Cambodia synthetic separate layers 1.0**, the approved legacy weighted-linear-combination method and **Balanced resilience**. State **synthetic demo** before starting. The asynchronous run should finish `succeeded_with_warnings`, with 111 results and checksum `741279cd97aed25f568c4dd8fc02cda6877acf3f65efe922af5d361db1841f54`.

Running this step adds durable governed run/output evidence. Skip it when the audience only needs a read-only tour; an existing successful run can be opened instead.

### 9. Results, contribution and lineage

Route: <http://localhost:3001/apps/investment-prioritisation/runs>, then open the newest successful **Cambodia synthetic separate layers 1.0** run.

Show map, ranking, contribution breakdown, warnings, exact input/method/scenario references, output dataset version and lineage. Expected rank 1 is **Prey Veng Demo Commune 03**, score `65.32`. Reiterate that the ranking is synthetic and not a recommendation.

### 10. Extension worklist

Persona: `dev-extension-officer-1`. Route: <http://localhost:3001/apps/extension-field-support/worklist>.

Show that Sreypov Mom sees assigned work such as `DEMO-001`, `DEMO-002` and `DEMO-005`, while unassigned or other-officer cases are not silently exposed. At a 390 × 844 viewport, show bottom navigation, connectivity state and the local demonstration boundary.

### 11. Observation through follow-up

Use seeded **demonstration records** so the normal tour stays read-only:

1. `DEMO-002` shows observation evidence.
2. `DEMO-003` shows a manual assessment and verification checklist.
3. `DEMO-004` shows an activity awaiting/recording supervisor review.
4. `DEMO-005` shows an overdue follow-up.
5. `DEMO-006` shows retained closed evidence.

Switch to `dev-extension-supervisor` and open <http://localhost:3001/apps/extension-field-support/supervision> to show assignment, overdue and approval summaries. Explain that field media is restricted, independently authorised and excluded from service-worker caches.

### 12. Governance, audit and health

Persona: `dev-admin`. Open <http://localhost:3001/governance/system-health>. Expected local status: database, object storage, Redis, worker and migrations `OK`; scanner `WARNING`; local backup evidence present; off-host backup false.

Switch to `dev-auditor` and open <http://localhost:3001/governance/audit>. Filter by action, actor, date or correlation ID and demonstrate CSV export. A viewer should not have this route.

### 13. Limitations and next work

Route: <http://localhost:3001/help/data-and-method-limitations>.

Close with the distinctions between real samples, synthetic results and fictional field records. Call out production SSO/scanning/deployment controls, unconfirmed licences, no business endorsement, no automated/agronomic advice, deferred PostGIS layer materialisation ([issue #4](https://github.com/MickeyRay0624/fao-climate-geospatial-platform/issues/4)) and deferred raster/COG tiles ([issue #5](https://github.com/MickeyRay0624/fao-climate-geospatial-platform/issues/5)).

## After the session

If the session only read existing evidence, no reset is necessary. If it created runs or changed cases, capture a new snapshot and use [DEMO_RESET_WITHOUT_DATA_LOSS.md](../runbooks/DEMO_RESET_WITHOUT_DATA_LOSS.md). Never use volume deletion as a reset.
