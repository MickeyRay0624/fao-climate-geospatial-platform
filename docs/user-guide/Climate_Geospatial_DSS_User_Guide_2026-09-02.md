# Climate Geospatial Data & Decision Platform

## User Guide, Capability Overview & Product Roadmap

**Cambodia Rice Resilience Demonstration · Hosted Team Review Edition**
**Version:** 0.3.0-demo-platform
**Document date:** 2 September 2026
**Live demonstration:** [https://dss.lmqstudio.com](https://dss.lmqstudio.com)

**Audience:** Programme leaders, data stewards, analysts, reviewers, extension teams, administrators and technical evaluators.

> **Evidence boundary**
> The hosted edition uses synthetic analysis data and fictional field cases. It demonstrates governed workflows, reproducibility and engineering capability; it is not operational planning advice, a funding recommendation, an agronomic diagnosis or an institutional endorsement.

<!-- PAGE BREAK -->

# 1. Start Here

## 1.1 What this system is

The Climate Geospatial Data & Decision Platform is a working, modular demonstration of how climate, agricultural and geospatial evidence can move through one controlled chain:

**ingest data → validate quality → review and publish → lock exact inputs → run a transparent method → inspect and export results → support field follow-up → retain audit evidence**

It is not simply a dashboard. Behind the visible screens are separate controls for identity, permissions, data versions, approval responsibilities, asynchronous processing, lineage, sensitive field records, audit and operational health. The result is a platform foundation that can support additional decision applications without rebuilding governance for every new module.

## 1.2 The fastest way to understand it

Open the live site and follow this ten-minute route:

1. Go to [https://dss.lmqstudio.com](https://dss.lmqstudio.com). No temporary access account or password is required for the current team-review period.
2. On **Home**, read the workspace name, evidence disclaimer, catalogue totals and role-specific task cards.
3. Use the amber **Development identity** selector to switch to **Vichea Pen** (Analyst).
4. Open **Investment Prioritisation → Runs**, then open the completed synthetic run.
5. Inspect its map, ranking, per-indicator contribution, warnings, lineage, checksum and downloadable assets.
6. Switch to **Sreypov Mom** or **Rithy Touch** (Extension Officer) and open **Extension Field Support → My worklist**.
7. Open a fictional case and trace observation, manual assessment, verification, activity and follow-up.
8. Switch to **Sokha Meas** (Extension Supervisor) to view team workload, unassigned work and overdue follow-ups.
9. Switch to **Samnang Khem** (Auditor) and open **Governance → Audit log**.
10. Finish as **Amina Sok** (Administrator) on **System health** to show databases, object storage, queue workers, migrations and scanner status.

> **Team-review safety rule**
> The demonstration is publicly reachable during review. Enter only synthetic, fictional or otherwise approved demonstration content. Do not upload confidential files, personal data, farmer names, telephone numbers or exact farm locations.

## 1.3 What is already working

| Capability | What a non-technical user can see | What the platform is doing underneath |
|---|---|---|
| Role-aware workspace | Each persona sees relevant menus and tasks | Capability-driven navigation with role and resource checks |
| Governed Data Hub | Browse, upload, review, publish, preview and download data | Immutable versions, checksums, validation, quarantine, signed access and lineage |
| Investment prioritisation | Run and explain an illustrative priority ranking | Locked inputs, approved versions, asynchronous execution, deterministic outputs and provenance |
| Extension field support | Manage fictional cases from observation to follow-up | Assignment scope, structured states, idempotent writes, sensitive media controls and approval evidence |
| Governance | Inspect people, roles, reviews, policies, retention and audit | Separation of duties, explicit-deny rules and append-only activity records |
| Operations | See system dependencies and queue state | PostgreSQL/PostGIS, object storage, Redis/Celery workers, migrations and health checks |

<!-- PAGE BREAK -->

# 2. How to Navigate the Platform

## 2.1 The application shell

The same interface surrounds every module so that users do not have to learn a new system for each workflow.

| Screen area | How to use it |
|---|---|
| Amber identity banner | Change the demonstration persona. This simulates different responsibilities; it is not production single sign-on. |
| Left navigation | Open Home, Data Hub, Applications, Governance and Help. Items change according to the active persona. |
| Active workspace card | Confirms the organizational boundary in which data and work are being viewed. |
| Global search | Search datasets, versions and analysis runs from one place. |
| Processing indicator | Shows queued or running background jobs. |
| User card | Confirms the current persona and role before taking an action. |
| Breadcrumb | Shows the current area and provides a path back to the workspace. |
| Help | Explains evidence labels, module workflows and current limitations. |

## 2.2 Why the persona selector matters

The platform models real separation of responsibilities. A contributor should not approve their own data; a method editor should not approve their own method; a field officer should not automatically see another officer's cases. The selector lets reviewers experience these controls without creating fourteen external accounts.

Changing persona can also clear restricted Extension drafts from browser session storage. Complete or copy any fictional draft before switching.

## 2.3 Recommended personas

| Persona | Demonstration responsibility | Best screens to open |
|---|---|---|
| Amina Sok | Platform administrator | Home, Members, Roles, Applications, System health |
| Dara Chann | Data contributor | My data, New dataset, Uploads |
| Sophea Lim | Data reviewer | Data reviews, Version quality and review |
| Nita Vann | Data publisher | Approved versions awaiting immutable publication |
| Vichea Pen | Analyst | Input sets, Methods, Scenarios, Runs, Compare |
| Chantha Ros | Method editor | Method and scenario authoring |
| Bopha Keo | Method approver | Independent method approval |
| Sreypov Mom / Rithy Touch | Extension officers | Worklist, Cases, Verification, Activities, Sync |
| Sokha Meas | Extension supervisor | Supervision, assignment, workload and approval |
| Pisey Heng | Knowledge editor | Versioned field knowledge content |
| Kunthea Sim | Knowledge approver | Independent knowledge approval |
| Samnang Khem | Auditor | Audit log, governance evidence and health |
| Maly Chea | Read-only viewer | Published catalogue and permitted results |

> **What this proves**
> The role changes are not visual theatre. Menu visibility, API authorization, resource ownership, review assignment and explicit deny decisions are evaluated separately. This is the basis for replacing demonstration personas with organizational identity groups later.

<!-- PAGE BREAK -->

# 3. Home, Search and Evidence Labels

## 3.1 Home

Home is a role-aware operational summary. It combines catalogue evidence, running work and actions permitted to the active persona.

Use it to answer four questions:

- **Where am I working?** Check the active workspace.
- **What evidence is available?** Review visible and published dataset counts.
- **What needs my attention?** Read role cards for drafts, reviews, runs, cases or system alerts.
- **What is safe to claim?** Read the demonstration disclaimer before presenting results.

## 3.2 Global search

Enter a dataset title, version label or run-related term in the top search field and press Enter. Results are permission-scoped: users do not receive search results for resources they are not allowed to view.

## 3.3 Read evidence labels literally

| Label | Meaning | Appropriate use |
|---|---|---|
| `SYNTHETIC_DEMO` | Deterministic, generated data used to prove a workflow | Training, demonstrations, software verification |
| Fictional field record | Invented case with no real farmer or exact farm | Demonstrating officer and supervisor workflow |
| Real source sample | A traceable source excerpt, when separately loaded and licensed | Data-pipeline validation only until formally accepted |
| Illustrative method | A transparent example method without business endorsement | Demonstrating reproducibility and explanation |
| Published version | A human-approved version frozen against silent changes | Reuse by governed processes, subject to licence and fitness decisions |

The currently hosted team edition contains **no real-source sample datasets**. Its ten visible datasets are intentionally labelled synthetic. This prevents a polished demonstration from being mistaken for validated operational evidence.

<!-- PAGE BREAK -->

# 4. Data Hub: From File to Governed Evidence

## 4.1 What the Data Hub does

The Data Hub is the evidence foundation for every analytical application. It manages logical datasets separately from their exact versions and files. This allows the platform to answer not only “what data did we use?” but also “which exact bytes, metadata, validation result, reviewer decision and licence statement did we use?”

## 4.2 Browse the catalogue

1. Open **Data Hub → Team catalogue**.
2. Filter by text, owner, data type, status, visibility, classification or evidence type.
3. Open a dataset to see its summary and versions.
4. Open a version to inspect files, quality, review status, preview, access and lineage.
5. Download only when the licence, classification and your permission allow it.

Collections can pin exact dataset versions. They do not silently follow a later release, which protects the reproducibility of projects and analyses.

## 4.3 Upload and publish a new demonstration dataset

Use **Dara Chann** as Data Contributor:

1. Open **Data Hub → New dataset**.
2. Add a clear title, purpose, type, visibility, classification and evidence label.
3. Create a version and select the appropriate validation profile.
4. Upload the source file. The browser sends it directly to object storage using a short-lived signed instruction; the API does not become a large-file relay.
5. Complete the upload. A background job records checksum, scan status, structural validation and quality issues.
6. Review the preview and quality findings.
7. Submit the version for independent review.

Switch to **Sophea Lim** as Data Reviewer:

8. Open **Data Hub → Reviews**.
9. Inspect metadata, file evidence, validation issues and preview.
10. Record an approval or rejection with rationale.

Switch to **Nita Vann** as Data Publisher:

11. Open the approved version and select **Publish**.
12. Confirm the publication. The published record becomes immutable rather than being silently overwritten later.

## 4.4 Supported validation paths today

| Profile | Implemented checks and behavior |
|---|---|
| Analysis-ready bundle | Validates the controlled demonstration bundle used by the investment workflow |
| Administrative boundary | Validates required geographic identifiers and vector structure |
| Normalized indicator layer | Validates area/value relationships for one analytical indicator |
| Generic vector | Accepts GeoJSON and a controlled one-layer WGS84 Shapefile ZIP or GeoPackage; registers a derived GeoJSON representation |
| Generic table | Previews and validates CSV tables with paginated access |
| Document | Handles PDF, DOCX, Markdown and text as governed assets; optical character recognition is not claimed |

## 4.5 What makes this more than file storage

- Exact versions are independently addressable and can be locked into collections or analysis input sets.
- Published records are protected by application logic and database-level immutability triggers.
- File checksums make later byte changes detectable.
- Review, publication, download and access changes create audit evidence.
- Permission grants can target users or groups; an explicit deny overrides broader allows.
- Lineage links inputs, transformations and outputs rather than leaving provenance in presentation notes.
- Short-lived signed URLs limit direct object access and avoid exposing storage credentials.

<!-- PAGE BREAK -->

# 5. Investment Prioritisation

## 5.1 Purpose

This module demonstrates a transparent, reproducible multi-criteria prioritisation workflow. It ranks 111 synthetic communes using seven synthetic indicators under an approved demonstration scenario. The purpose is to show how a decision workflow can be governed and explained—not to recommend real investments.

## 5.2 Open the completed demonstration run

1. Select **Vichea Pen** in the Development identity banner.
2. Open **Applications → Investment Prioritisation → Runs**.
3. Open the most recent completed run.
4. Review its status. `Succeeded with warnings` means the run finished but transparently recorded input warnings.
5. Open **Map** to see priority bands spatially.
6. Open **Ranking** to sort and inspect the 111 results.
7. Select an area to see the seven indicator values, weights and score contributions.
8. Open **Lineage** to see the exact input set, method version, scenario and derived output dataset.
9. Open **Assets / Export** to access the CSV ranking, GeoJSON ranking and JSON run manifest through short-lived links.
10. Use **Compare** when more than one governed run is available.

## 5.3 How to interpret a score

The demonstration method is a deterministic weighted linear combination. Each indicator is normalized, multiplied by its approved scenario weight and added to the total. The area explanation shows how much each factor contributed, so the result is not a black box.

For the current hosted run, the top synthetic result is **Prey Veng Demo Commune 03**, with a demonstration score of **65.32**. Its components include yield gap, flood risk, drought risk, poverty, irrigation gap, nature-based-solutions opportunity and market isolation. This result is generated evidence, not a real commune recommendation.

## 5.4 Create a new run

1. Open **Input sets** and select a locked set containing the exact boundary version and all seven indicator versions.
2. Confirm that the set is valid and locked. Locking prevents an input from changing while a decision is being reproduced.
3. Select an approved method version.
4. Select an approved scenario with permitted weights and parameters.
5. Review assumptions, missing-data warnings and evidence labels.
6. Start the run. The request returns immediately while a queue worker performs the computation.
7. Monitor progress through the job indicator or run page.
8. When complete, inspect the checksum, results, warnings, lineage and registered output dataset.

## 5.5 Technical controls behind the workflow

| Control | Why it matters |
|---|---|
| Locked input set | Reproduction always refers to the same dataset versions |
| Versioned method and scenario | A methodology change cannot reinterpret a historical result |
| Independent approval | The editor cannot silently approve their own method |
| Idempotent run request | Repeated submission does not create accidental duplicate work |
| Asynchronous worker | Long-running analysis does not block the web application |
| Deterministic result checksum | The output can be compared across executions |
| Warning and exclusion records | Missing data is exposed rather than hidden |
| Registered derived dataset | Results re-enter the governed catalogue with provenance |
| CSV, GeoJSON and manifest assets | Humans, GIS tools and machines can use the same result |

> **Do not present the ranking as real**
> The current hosted run uses synthetic boundaries, indicators and an illustrative method. Formal ownership, source validation, licence decisions, sensitivity analysis and business approval are required before any operational prioritisation.

<!-- PAGE BREAK -->

# 6. Extension Field Support

## 6.1 Purpose

The Extension Field Support module demonstrates a mobile-oriented case workflow connecting structured field observation, human verification, approved knowledge, activity planning and follow-up. It deliberately does not automate diagnosis or agronomic advice.

The hosted edition contains **eight fictional cases**, including workload, assignment, overdue follow-up and approval examples. No real farmer, phone number or exact farm is used.

## 6.2 Officer workflow

Use **Sreypov Mom** or **Rithy Touch**:

1. Open **Extension Field Support → My worklist**.
2. Filter active cases by text or status.
3. Open a case assigned to the active officer.
4. Record a structured observation with visible conditions and context.
5. Select a possible-cause category manually from demonstration knowledge; the platform does not generate an automated diagnosis.
6. Complete the versioned verification checklist and record evidence.
7. Plan an approved activity or field follow-up.
8. Record the follow-up outcome and close the case when complete.
9. Open **Sync** to see connectivity, pending draft and idempotent synchronization information.

To create a demonstration case, use an invented summary and approximate fictional location. Never enter personal information or precise coordinates.

## 6.3 Supervisor workflow

Use **Sokha Meas**:

1. Open **Extension Field Support → Supervision**.
2. Review team workload, unassigned cases and overdue follow-ups.
3. Assign or reassign a case within the authorized workspace.
4. Review priorities, officer evidence and pending activities.
5. Approve or reject a controlled activity with a reason.
6. Confirm that changes appear in the audit trail.

## 6.4 Privacy and integrity controls

- Officers are limited to cases they own or are assigned, unless a narrower or explicit grant applies.
- Supervisors see workload within their authorized programme scope.
- Completed records are protected from silent mutation by database triggers.
- Mutating requests use client identifiers or idempotency keys to prevent duplicate records after retries.
- Media is classified as sensitive field content, restricted by assignment and delivered through short-lived signed URLs.
- Supported demonstration media types are JPEG, PNG and WebP up to 10 MB, with SHA-256 evidence.
- Sensitive API and media responses are excluded from normal service-worker caching.
- Raw field cases are never automatically promoted to the shared Data Hub.

## 6.5 Current offline boundary

The Sync screen demonstrates connectivity state, local draft counts and exactly-once synchronization metadata. It is not yet a production encrypted offline database, conflict-resolution engine or background media uploader. Production field use requires encrypted local storage, tested conflict policies, device revocation, session expiry, privacy review and operational validation.

<!-- PAGE BREAK -->

# 7. Governance, Audit and Operations

## 7.1 Governance workspace

Administrators and reviewers can inspect:

- members synchronized from an identity boundary;
- groups and membership;
- roles, assignments and time-bounded access;
- data policies and classifications;
- dataset, method, knowledge and activity review queues;
- quality profiles;
- application contracts and feature flags;
- retention and legal-hold concepts;
- audit events and operational health.

Some policy pages are intentionally read-only until organizational decisions are approved. Showing an unresolved control is stronger than presenting a default as an institutional policy.

## 7.2 Audit log

Use **Samnang Khem** or **Amina Sok** and open **Governance → Audit log**.

Filter by actor, action, resource, outcome, date or correlation identifier. Export permitted evidence to CSV when needed. Important events include upload, validation, review, publication, download, grants, denied access, method approvals, run creation, field assignments, media access and supervisor decisions.

The correlation identifier links a user-visible error or action to structured backend logs without exposing secrets.

## 7.3 System health

Open **Governance → System health** as Administrator. The current hosted edition reports:

| Service | Current state | Meaning |
|---|---|---|
| PostgreSQL/PostGIS database | OK | Transactional, spatial and governance records are reachable |
| Object storage | OK | Governed files and derived assets are reachable |
| Redis | OK | Queue coordination is reachable |
| Celery worker | OK | One background worker is responding |
| Database migrations | OK | Runtime schema matches migration `20260901_0005` |
| Queue depth | 0 | No work is waiting at the time of the snapshot |
| Malware scanner | Warning | Hosted demo uses an explicit development bypass, not an approved production scanner |
| In-app backup evidence | Not available | Off-host backup evidence is not mounted into the application health view |

## 7.4 Operational architecture

The hosted application uses HTTPS and a custom domain in front of a containerized deployment. The runtime is designed as a modular monolith: one deployable backend with strongly separated domain schemas and routers. This keeps early operations manageable while retaining clear extraction boundaries for future services.

<!-- PAGE BREAK -->

# 8. Current Hosted Demonstration: Evidence Snapshot

The following figures were verified against the live hosted environment and source repository on **2 September 2026**.

## 8.1 Live product evidence

| Measure | Verified value |
|---|---:|
| Visible datasets | 10 |
| Published datasets | 9 |
| Real-source samples in hosted instance | 0 |
| Synthetic analytical areas | 111 |
| Indicator values | 777 (7 × 111) |
| Locked analysis input sets | 2 |
| Approved scenarios | 4 |
| Native completed runs | 1 |
| Ranked results in current run | 111 |
| Signed run assets | 3: CSV, GeoJSON and JSON manifest |
| Fictional Extension cases | 8 |
| Overdue demonstration follow-ups | 2 |
| Development personas | 14 |
| Workspace members | 15 |
| Enabled application modules | 2 |

The completed run produced result checksum `741279cd97aed25f568c4dd8fc02cda6877acf3f65efe922af5d361db1841f54`. Checksums are shown here as technical evidence of deterministic, immutable output—not as a business-validity claim.

## 8.2 Engineering footprint

| Engineering measure | Verified value | Why it matters |
|---|---:|---|
| Application source | 26,425 physical lines | Substantial implemented backend, frontend and styling surface |
| Backend route handlers | 147 | Broad user, data, analysis, field, governance and operations API |
| ORM-backed tables | 70 | Explicit domain state rather than a thin visualization layer |
| Domain database schemas | 8 | `iam`, `core`, `governance`, `catalog`, `jobs`, `audit`, `investment`, `extension` |
| Alembic migration revisions | 5 | Repeatable schema evolution through a controlled migration chain |
| Automated backend tests | 63 | Authorization, ingestion, validators, governance, investment and extension behavior |
| Automated frontend tests | 11 | User-interface contracts and role-aware behavior |
| Dedicated end-to-end/smoke entry points | 5 | Data Hub, negative controls, investment, full demo and browser smoke paths |
| Declared module screens | 21 | Contracted routes across the two optional application modules |

**Counting note:** Source figures cover Python, TypeScript/TSX and CSS under `api/app` and `web/src`; route and test counts are static source counts. They communicate engineering scope, not a substitute for quality or business acceptance.

## 8.3 The workload represented by the product

The visible application required coordinated work across:

- domain and information architecture;
- responsive interaction design and a shared application shell;
- identity abstraction, roles, permissions and resource grants;
- relational and spatial data modelling across seventy tables;
- migrations, data seeding and legacy-analysis reconciliation;
- object-storage upload, signed access and derived asset registration;
- background queues, progress, idempotency and failure handling;
- vector and tabular validation and preview;
- reproducible analysis, score explanation and exports;
- field case state machines and sensitive-media boundaries;
- review, publication, audit and health interfaces;
- containerization, reverse proxy, custom domain, TLS and public cloud deployment;
- automated unit, integration, negative-control, end-to-end and smoke verification.

This is why the platform should be evaluated as a reusable digital public infrastructure foundation, not only by the number of visible pages.

<!-- PAGE BREAK -->

# 9. Technical Architecture at a Glance

## 9.1 Layered design

| Layer | Implemented components | Design value |
|---|---|---|
| User experience | React, TypeScript, responsive SPA, maps, role-aware navigation, PWA shell | One consistent experience across data, analysis and field workflows |
| API and domain services | FastAPI modular routers, contract-first error envelopes, correlation IDs | Clear module boundaries and predictable integration surface |
| Decision applications | Investment Prioritisation and Extension Field Support | New applications reuse identity, data, jobs and audit foundations |
| Governance services | Identity, permissions, reviews, policies, audit, retention, module registry | Controls are shared rather than reimplemented per module |
| Processing | Celery workers, Redis queue, validation jobs, analysis jobs, export jobs | Long tasks are durable, observable and isolated from web requests |
| Data and files | PostgreSQL/PostGIS, MinIO-compatible object storage, immutable checksums | Structured records, spatial capability and governed large assets |
| Delivery | Docker Compose, Nginx reverse proxy, custom domain and TLS | Reproducible cloud deployment with a low operational footprint |

## 9.2 End-to-end evidence flow

| Stage | Input | Control | Output |
|---|---|---|---|
| 1. Register | Dataset purpose and metadata | Workspace, owner, visibility and classification | Logical dataset |
| 2. Upload | Source file | Short-lived direct upload to quarantine | Immutable asset candidate |
| 3. Validate | Asset bytes and profile | Checksum, scan state, structure and quality issues | Quality evidence |
| 4. Review | Metadata, preview and issues | Independent human decision with rationale | Approved version |
| 5. Publish | Approved version | Publisher authority and database immutability | Reusable governed evidence |
| 6. Analyse | Locked exact versions | Approved method/scenario and async job | Ranked output and checksum |
| 7. Register result | CSV, GeoJSON, manifest | Lineage and derived-dataset registration | Governed analytical product |
| 8. Act and follow up | Priorities or field assignment | Human confirmation and restricted cases | Structured action evidence |
| 9. Audit | Every critical transition | Actor, resource, outcome and correlation ID | Traceable decision record |

## 9.3 Design decisions that protect future growth

- **Modular monolith first:** operational simplicity now, extraction boundaries later.
- **Authoritative namespaces:** each domain owns its write model; modules do not write directly into one another's tables.
- **Immutable evidence:** published data and historical analysis remain interpretable after methods or interfaces evolve.
- **Shared platform contracts:** every module declares routes, permissions, data profiles, jobs, security, observability, offline behavior and retirement policy.
- **Human authority:** review and field confirmation are explicit; the platform does not disguise automation as approved expert judgment.
- **Capability-driven UI:** navigation follows authorization rather than relying on hidden buttons as security.
- **Idempotent mutation:** retry-safe operations protect users working through unstable networks.

<!-- PAGE BREAK -->

# 10. Security, Integrity and Reproducibility

## 10.1 Implemented controls

| Area | Implemented control |
|---|---|
| Identity boundary | Development personas sit behind an abstraction designed for later OIDC integration |
| Authorization | Role, capability, ownership, review assignment, workspace and resource grants |
| Denial rules | Explicit deny takes precedence over broader allow; denied access can be audited |
| Separation of duties | Contributors, reviewers, publishers, editors and approvers are distinct responsibilities |
| Data integrity | Checksums, immutable published records, optimistic row versions and database triggers |
| Reproducibility | Exact dataset versions, method version, scenario, parameters, lineage and result checksum |
| File access | Quarantine workflow and short-lived signed upload/download links |
| Sensitive field data | Assignment-scoped access, restricted media, safe log fields and cache avoidance |
| Request tracing | Validated correlation identifiers and structured error envelopes |
| Operational evidence | Health checks for dependencies, worker, migrations, queue and scanner mode |

## 10.2 What is intentionally not claimed yet

The current public team edition uses development identity and a scanner bypass. Production single sign-on, approved malware scanning, managed secrets, least-privileged database roles, centralized immutable audit export, security monitoring, off-host backup evidence and incident procedures remain production-hardening work.

This distinction is a strength: the platform exposes the state of controls and blocks inflated operational claims instead of hiding gaps behind a polished interface.

<!-- PAGE BREAK -->

# 11. Product Roadmap

The roadmap below is a proposed sequence, not a promise of delivery dates. Each phase requires an accountable product owner, data or method owner, security review and acceptance criteria.

## Phase 1 — Production hardening

**Objective:** move from open team demonstration to a controlled pilot.

- Integrate organizational OIDC / single sign-on and remove development persona switching.
- Add approved malware scanning and fail closed for unscanned uploads.
- Move secrets to a managed store; use least-privileged runtime and database identities.
- Add production ingress controls, rate limits, environment separation and access reviews.
- Centralize structured logs and immutable audit export into the approved SIEM/monitoring service.
- Configure alerts, service objectives, incident runbooks and tested restore procedures.
- Produce visible, off-host backup evidence and recovery testing results.
- Confirm data classifications, retention periods, licences and responsible owners.

## Phase 2 — Data scale and interoperability

**Objective:** support larger and more diverse geospatial holdings.

- Add robust multi-layer vector selection, reprojection and controlled PostGIS materialization.
- Add reviewed GeoTIFF/Cloud Optimized GeoTIFF validation, raster metadata and authorized tile delivery.
- Add STAC-compatible metadata and stronger OGC/interoperability interfaces.
- Add multipart/resumable upload for larger files and unstable connections.
- Add GeoParquet and governed PDF/report exports.
- Expand metadata quality, licence workflows, catalogue integration and reusable collections.

## Phase 3 — Decision intelligence maturity

**Objective:** convert the illustrative method into institutionally governed decision support.

- Appoint method owners and complete independent methodology validation.
- Load validated boundaries, climate, agricultural, vulnerability and investment datasets.
- Enable formal sensitivity analysis and uncertainty communication.
- Add public-result publication as a separate reviewed workflow.
- Introduce additional decision modules through the existing module contract.
- Add temporal comparison, climate scenarios and reproducible model/container orchestration.

## Phase 4 — Field mobility and learning loop

**Objective:** support operational extension teams in low-connectivity environments.

- Approve and localize versioned knowledge content in English and Khmer.
- Implement encrypted offline storage, background synchronization and media upload.
- Test conflict resolution, device revocation, remote wipe and session-expiry behavior.
- Complete privacy, consent, retention and safeguarding review for field records.
- Add operational supervision metrics without exposing personal or precise-location data.
- Enable de-identified, approved aggregate publication from Extension to Data Hub.

## Phase 5 — Validated digital-twin capabilities

**Objective:** evolve toward dynamic monitoring and simulation only after evidence governance is operational.

- Integrate governed remote-sensing, weather, field and programme observations.
- Add near-real-time indicators, event monitoring and temporal state histories.
- Add scenario simulation, model ensembles and decision-feedback measurement.
- Calibrate outputs against field outcomes and publish model-performance evidence.
- Use “digital twin” positioning only when the system represents validated, updated real-world state—not merely because it contains a map.

<!-- PAGE BREAK -->

# 12. Current Limitations and Readiness Decisions

## 12.1 Demonstration limitations

- Hosted data is synthetic; no operational dataset has been approved in this instance.
- The investment method and scenarios are illustrative and not business-endorsed.
- Field records and locations are fictional; knowledge sources are placeholders.
- There is no automated diagnosis, agronomic prescription or funding recommendation.
- The public team-review deployment has no temporary password gate and must not hold sensitive information.
- Development identity is not organizational SSO.
- The upload scanner is in explicit development-bypass mode.
- Production offline storage and conflict handling are not complete.
- Raster/COG/STAC processing, raster tiles and large multipart uploads are deferred.
- GeoParquet/PDF analytical exports and full production telemetry/SIEM are deferred.
- Licences, data fitness, retention and method ownership require formal decisions.

## 12.2 What the current version is ready for

| Use | Readiness |
|---|---|
| Stakeholder demonstration and usability review | Ready, using only demonstration content |
| Architecture and engineering review | Ready |
| Workflow, permission and governance evaluation | Ready |
| Synthetic training and reproducibility walkthrough | Ready |
| Controlled pilot with real non-sensitive data | Not yet; production controls and approvals required |
| Operational investment decision | Not ready |
| Real farmer case management | Not ready |
| Automated agronomic advice | Out of scope for the current system |

## 12.3 Decision gate before a real pilot

A real pilot should begin only when the following have named owners and acceptance evidence:

1. Organizational identity and access model.
2. Data sources, licences, classifications and retention.
3. Approved validation and malware-scanning process.
4. Method owner, version, validation and uncertainty policy.
5. Field privacy, consent, safeguarding and offline-device policy.
6. Hosting, backups, monitoring, incident response and support responsibility.
7. Training, localization, user acceptance and operational success measures.

<!-- PAGE BREAK -->

# 13. Fifteen-Minute Demonstration Script

## Minute 0–2: Position the platform

Open Home and say:

> “This is a governed data and decision platform, not a static dashboard. The hosted edition uses synthetic and fictional evidence so that we can demonstrate the complete workflow without implying operational validity.”

Point out the workspace, persona banner, catalogue totals, task cards and evidence disclaimer.

## Minute 2–5: Show governed data

Open Team catalogue and one synthetic dataset. Show the logical dataset, exact version, evidence type, quality, access and lineage. Explain the contributor → reviewer → publisher separation and immutable publication.

## Minute 5–9: Show reproducible analysis

Switch to Vichea Pen. Open the completed investment run. Show:

- locked exact inputs and approved scenario;
- asynchronous status and warnings;
- map and 111 ranked results;
- one area's seven score contributions;
- deterministic checksum;
- CSV, GeoJSON and JSON manifest;
- output registered back into Data Hub with lineage.

Say:

> “The technical achievement is not only the score. It is the ability to explain, reproduce, govern and audit how the score was produced.”

## Minute 9–12: Show the field workflow

Switch to an Extension Officer and open a fictional assigned case. Trace observation → manual assessment → verification → activity → follow-up. Emphasize that the officer confirms evidence and that there is no automated diagnosis.

Switch to Sokha Meas and show workload, unassigned cases and overdue follow-ups.

## Minute 12–15: Prove control and readiness

Switch to Samnang Khem and show audit filters. Then switch to Amina Sok and open System health. Point out healthy dependencies and the visible scanner warning.

Close with:

> “The system already demonstrates the hard platform foundations—versioned evidence, permissions, separation of duties, asynchronous processing, lineage, field operations and audit. The next investment is to validate real data and methods, harden identity and security, and scale the geospatial and offline capabilities.”

<!-- PAGE BREAK -->

# Appendix A. Quick Troubleshooting

| Symptom | What to check |
|---|---|
| A menu item is missing | Confirm the active persona; navigation is capability-driven |
| A case is unavailable | Use the assigned officer or authorized supervisor persona |
| A contributor cannot publish | Switch to the independent reviewer, then publisher |
| A method editor cannot approve | Switch to the method approver; self-approval is intentionally blocked |
| A run shows warnings | Open warnings and area explanations; warnings are preserved intentionally |
| An upload remains queued | Open Processing jobs and System health; check worker and queue state |
| A download link expired | Request a new signed link; links are intentionally short-lived |
| A field draft disappeared after persona change | Persona switching clears restricted Extension session drafts |
| A real-data run cannot be created | The hosted instance has no complete, validated real input set |
| An error needs investigation | Record the correlation ID shown in the response and provide it to the platform operator |

# Appendix B. Glossary

| Term | Plain-English meaning |
|---|---|
| Asset | A stored file, such as a CSV, GeoJSON, document or image |
| Checksum | A digital fingerprint used to detect byte changes |
| Classification | The sensitivity level controlling handling and access |
| Collection | A curated set that pins exact dataset versions |
| Correlation ID | A request identifier connecting a screen action to system logs |
| Data profile | A versioned set of structural and quality expectations |
| Dataset | The continuing logical data product, independent of any one file |
| Dataset version | One exact release of a dataset and its files |
| Derived dataset | A governed output produced from other inputs, such as a ranking |
| Evidence label | A statement such as synthetic, fictional or real-source sample |
| Idempotency | Retry behavior that avoids creating duplicate work |
| Lineage | The trace from sources through processing to outputs |
| Locked input set | Exact versions frozen for one reproducible analysis configuration |
| Method version | An immutable description of how an analytical result is calculated |
| Persona | A development-only simulated user responsibility |
| Published | Human-approved and protected from silent alteration |
| Scenario | A versioned set of permitted weights or parameters |
| Signed URL | A short-lived link granting limited access to one stored asset |
| Workspace | The organizational boundary for people, data and workflows |

---

**Document status:** English team-review guide for the hosted demonstration.
**Source basis:** live platform responses, source implementation, module contracts, architecture decisions and release documentation verified on 2 September 2026.
