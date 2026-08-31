# ADR-004: PostGIS metadata and S3-compatible object storage

- Status: Accepted
- Date: 2026-08-31

## Context

Catalog relations, geometry, access policy, lifecycle, lineage, jobs, and audit need transactional queries and constraints. Original/derived files may be large and must retain byte identity. Storing blobs in PostgreSQL or relational state only in object metadata would weaken either concern.

## Decision

Use PostgreSQL/PostGIS for authoritative relational/spatial state and MinIO/S3-compatible storage for file bytes. Store object key, size, media type, SHA-256, scan state, role, and version relation in `catalog.assets`. Upload through short-lived signed PUT into quarantine; after successful processing, copy into a versioned catalog prefix. Download uses short-lived signed GET. Separate internal and browser-facing endpoints.

## Consequences

- Database and object backups must be coordinated.
- Browser never receives permanent object credentials.
- Checksums and immutable catalog references provide provenance.
- Archive retains bytes; lifecycle retention and physical deletion require a later governed policy.
- Multipart/raster-scale transport remains future work.
