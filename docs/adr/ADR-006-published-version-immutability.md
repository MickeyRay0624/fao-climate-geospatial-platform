# ADR-006: Published version immutability

- Status: Accepted
- Date: 2026-08-31

## Context

Analysis, review, download, and audit must refer to the exact approved bytes and metadata. Editing a published record in place would make past decisions irreproducible. Service checks alone do not protect against future code or direct SQL mistakes.

## Decision

At publication, require approved state, reviews, quality/scan policy, metadata, authorization, optimistic lock, and duty separation. Freeze `metadata_snapshot`, actor/timestamps, and set the dataset current published pointer. Reject changes to published/deprecated/archived version business fields and to their assets/representations in both service code and PostgreSQL triggers. Corrections create a new version linked by `supersedes_version_id`; deprecation/archive never rewrite evidence.

## Consequences

- Published citations and historic analyses remain reproducible.
- Metadata correction costs a new governed version.
- Operational fields must be deliberately excluded from the immutable business-field trigger.
- Downgrade cannot safely erase publication evidence; backup restore is the rollback path.
