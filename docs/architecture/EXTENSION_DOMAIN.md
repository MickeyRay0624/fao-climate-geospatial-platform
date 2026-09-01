# Extension Field Support domain

## Purpose and boundary

Extension Field Support is a thin, manual demonstration workflow for assigned field cases. It records observations and human decisions; it does not diagnose crop conditions, generate advice, identify people or represent operational FAO field activity.

The module is enabled through the platform registry and uses platform identity, workspace membership, permissions, audit, object storage and health conventions. Its business state is isolated in the `extension` schema and its object keys use an `extension/<workspace>/<case>/media/` prefix.

## Domain records

| Aggregate | Tables | Role |
|---|---|---|
| Case and assignment | `cases`, `case_assignments`, `case_status_history` | Case identity, priority, state, current assignment and append-only transition evidence. |
| Observation and media | `observations`, `media_assets` | Structured/manual notes plus separately authorised field images. |
| Knowledge | `knowledge_items`, `knowledge_versions`, `knowledge_sources` | Versioned demonstration content and source placeholders with independent approval. |
| Assessment | `assessment_candidates` | Officer-selected candidate and rationale; never an automated diagnosis. |
| Verification | `verification_template_versions`, `verification_items`, `verification_sessions`, `verification_responses` | Versioned checklist and human responses. |
| Action and follow-up | `activity_plans`, `activity_steps`, `follow_ups` | Planned activity, supervisor approval, scheduled follow-up and completion evidence. |

## State and duties

Cases progress through `NEW`, `ASSIGNED`, `IN_OBSERVATION`, `IN_VERIFICATION`, `ACTION_PLANNED`, `FOLLOW_UP`, and `CLOSED`; `CANCELLED` requires a reason. The API checks allowed transitions and optimistic `row_version` values.

- An officer sees assigned cases and may add or complete their own permitted records.
- A supervisor sees the wider workspace worklist, assigns cases, reviews assessments and approves activities.
- A knowledge editor creates a version; a different knowledge approver approves it.
- Assignment and permission checks are applied by the API even if a route is manually requested.
- Completed observations, completed verification evidence and case history are protected from rewrite by database triggers.

All mutations require an `Idempotency-Key` of at least eight characters and emit audit evidence with the request correlation ID.

## Media boundary

Only JPEG, PNG and WebP images up to 10 MB are accepted. The API calculates SHA-256, applies the scanner boundary and records classification `SENSITIVE_FIELD`. Development uses a visible bypass status; production configuration fails closed without an approved scanner. A view requires the dedicated sensitive-media permission and a clean status, returns a short-lived signed URL, and is audited.

The PWA service worker caches same-origin shell/static resources only. It explicitly skips Extension API responses and media so sensitive case content is not persisted in the browser cache.

## Offline demonstration

The Sync view demonstrates connectivity state, pending-draft counts and idempotent synchronization metadata. It is not a production offline database, conflict-resolution engine or background media uploader. Local browser drafts must contain only demonstration content. Production offline support requires encrypted storage, remote-wipe/session-expiry design, data-minimisation review and tested conflict handling.

## Seed and reset behavior

The idempotent seed creates eight deterministic cases covering assigned/unassigned, observations, verification, activity approval, follow-up and closed-state examples. It also creates demonstration knowledge and verification template versions. Re-running seed does not overwrite altered business evidence or create duplicates.

Use the non-destructive reset procedure in [DEMO_RESET_WITHOUT_DATA_LOSS.md](../runbooks/DEMO_RESET_WITHOUT_DATA_LOSS.md). Never delete Compose volumes to reset the demonstration.
