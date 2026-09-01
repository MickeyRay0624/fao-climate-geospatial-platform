\set ON_ERROR_STOP on

DO $guard$
DECLARE blocked boolean := false;
BEGIN
  BEGIN
    UPDATE audit.events
       SET action = action || '.tamper-attempt'
     WHERE id = (SELECT id FROM audit.events ORDER BY event_time LIMIT 1);
  EXCEPTION WHEN SQLSTATE '55000' THEN
    blocked := true;
  END;
  IF NOT blocked THEN
    RAISE EXCEPTION 'append-only audit guard did not reject an update';
  END IF;
  RAISE NOTICE 'PASS: audit.events rejected mutation';
END $guard$;

DO $guard$
DECLARE blocked boolean := false;
BEGIN
  BEGIN
    TRUNCATE audit.events;
  EXCEPTION WHEN SQLSTATE '55000' THEN
    blocked := true;
  END;
  IF NOT blocked THEN
    RAISE EXCEPTION 'append-only audit guard did not reject truncate';
  END IF;
  RAISE NOTICE 'PASS: audit.events rejected truncate';
END $guard$;

DO $guard$
DECLARE blocked boolean := false;
BEGIN
  BEGIN
    UPDATE catalog.dataset_versions
       SET version_label = version_label || '-tamper-attempt'
     WHERE id = (
       SELECT id FROM catalog.dataset_versions
        WHERE state = 'PUBLISHED'
        ORDER BY published_at DESC NULLS LAST
        LIMIT 1
     );
  EXCEPTION WHEN SQLSTATE '55000' THEN
    blocked := true;
  END;
  IF NOT blocked THEN
    RAISE EXCEPTION 'published-version guard did not reject a metadata update';
  END IF;
  RAISE NOTICE 'PASS: published version rejected metadata mutation';
END $guard$;

DO $guard$
DECLARE blocked boolean := false;
BEGIN
  BEGIN
    UPDATE catalog.metadata_records metadata
       SET title = title || '-tamper-attempt'
      FROM catalog.dataset_versions version
     WHERE version.id = metadata.dataset_version_id
       AND version.state = 'PUBLISHED';
  EXCEPTION WHEN SQLSTATE '55000' THEN
    blocked := true;
  END;
  IF NOT blocked THEN
    RAISE EXCEPTION 'published metadata-record guard did not reject an update';
  END IF;
  RAISE NOTICE 'PASS: published metadata record rejected mutation';
END $guard$;

DO $guard$
DECLARE blocked boolean := false;
BEGIN
  BEGIN
    UPDATE catalog.assets
       SET filename = filename || '.tamper-attempt'
     WHERE id = (
       SELECT asset.id
         FROM catalog.assets asset
         JOIN catalog.dataset_versions version ON version.id = asset.dataset_version_id
        WHERE version.state = 'PUBLISHED'
        ORDER BY asset.created_at DESC
        LIMIT 1
     );
  EXCEPTION WHEN SQLSTATE '55000' THEN
    blocked := true;
  END;
  IF NOT blocked THEN
    RAISE EXCEPTION 'published-asset guard did not reject an update';
  END IF;
  RAISE NOTICE 'PASS: published asset rejected mutation';
END $guard$;

DO $guard$
DECLARE blocked boolean := false;
BEGIN
  BEGIN
    UPDATE catalog.review_decisions
       SET rationale = rationale || '-tamper-attempt'
     WHERE id = (SELECT id FROM catalog.review_decisions ORDER BY decided_at LIMIT 1);
  EXCEPTION WHEN SQLSTATE '55000' THEN
    blocked := true;
  END;
  IF NOT blocked THEN
    RAISE EXCEPTION 'append-only review decision guard did not reject an update';
  END IF;
  RAISE NOTICE 'PASS: review decision rejected mutation';
END $guard$;
