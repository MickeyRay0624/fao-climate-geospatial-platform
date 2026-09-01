"""Harden lifecycle constraints and append-only/immutable records.

Revision ID: 20260831_0002
Revises: 20260831_0001
"""

from alembic import op


revision = "20260831_0002"
down_revision = "20260831_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing databases predate the ORM check constraints, while a clean
    # bootstrap may already have them because revision 0001 uses current model
    # metadata. Guard by constraint name so both paths converge safely.
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_catalog_dataset_visibility') THEN
            ALTER TABLE catalog.datasets ADD CONSTRAINT ck_catalog_dataset_visibility
            CHECK (visibility IN ('PRIVATE','RESTRICTED','WORKSPACE','TEAM','FAO_INTERNAL','PUBLIC'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_catalog_dataset_classification') THEN
            ALTER TABLE catalog.datasets ADD CONSTRAINT ck_catalog_dataset_classification
            CHECK (classification IN ('PUBLIC','FAO_INTERNAL','RESTRICTED','SENSITIVE_FIELD'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_catalog_dataset_lifecycle') THEN
            ALTER TABLE catalog.datasets ADD CONSTRAINT ck_catalog_dataset_lifecycle
            CHECK (lifecycle_status IN ('ACTIVE','ARCHIVED'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_catalog_dataset_version_state') THEN
            ALTER TABLE catalog.dataset_versions ADD CONSTRAINT ck_catalog_dataset_version_state
            CHECK (state IN (
              'DRAFT','UPLOADING','PROCESSING','VALIDATION_FAILED','VALIDATED',
              'IN_REVIEW','CHANGES_REQUESTED','APPROVED','PUBLISHED','DEPRECATED','ARCHIVED'
            ));
          END IF;
        END $$;
        """
    )

    # Check both OLD and NEW parents on UPDATE. This closes the otherwise subtle
    # path where a child row could be moved from a draft into a published version.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION catalog.protect_published_child() RETURNS trigger AS $$
        DECLARE immutable_parent boolean;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            SELECT EXISTS (
              SELECT 1 FROM catalog.dataset_versions
              WHERE id = NEW.dataset_version_id AND state IN ('PUBLISHED','DEPRECATED','ARCHIVED')
            ) INTO immutable_parent;
          ELSIF TG_OP = 'DELETE' THEN
            SELECT EXISTS (
              SELECT 1 FROM catalog.dataset_versions
              WHERE id = OLD.dataset_version_id AND state IN ('PUBLISHED','DEPRECATED','ARCHIVED')
            ) INTO immutable_parent;
          ELSE
            SELECT EXISTS (
              SELECT 1 FROM catalog.dataset_versions
              WHERE id IN (OLD.dataset_version_id, NEW.dataset_version_id)
                AND state IN ('PUBLISHED','DEPRECATED','ARCHIVED')
            ) INTO immutable_parent;
          END IF;
          IF immutable_parent THEN
            RAISE EXCEPTION 'children of published dataset versions are immutable' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_published_asset ON catalog.assets;
        CREATE TRIGGER protect_published_asset
          BEFORE INSERT OR UPDATE OR DELETE ON catalog.assets
          FOR EACH ROW EXECUTE FUNCTION catalog.protect_published_child();

        DROP TRIGGER IF EXISTS protect_published_representation ON catalog.representations;
        CREATE TRIGGER protect_published_representation
          BEFORE INSERT OR UPDATE OR DELETE ON catalog.representations
          FOR EACH ROW EXECUTE FUNCTION catalog.protect_published_child();

        DROP TRIGGER IF EXISTS protect_published_metadata ON catalog.metadata_records;
        CREATE TRIGGER protect_published_metadata
          BEFORE INSERT OR UPDATE OR DELETE ON catalog.metadata_records
          FOR EACH ROW EXECUTE FUNCTION catalog.protect_published_child();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.reject_append_only_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION '%.% is append-only', TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = '55000';
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS review_decisions_append_only ON catalog.review_decisions;
        CREATE TRIGGER review_decisions_append_only
          BEFORE UPDATE OR DELETE ON catalog.review_decisions
          FOR EACH ROW EXECUTE FUNCTION core.reject_append_only_mutation();
        DROP TRIGGER IF EXISTS review_decisions_no_truncate ON catalog.review_decisions;
        CREATE TRIGGER review_decisions_no_truncate
          BEFORE TRUNCATE ON catalog.review_decisions
          FOR EACH STATEMENT EXECUTE FUNCTION core.reject_append_only_mutation();

        DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit.events;
        CREATE TRIGGER audit_events_no_truncate
          BEFORE TRUNCATE ON audit.events
          FOR EACH STATEMENT EXECUTE FUNCTION core.reject_append_only_mutation();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Security hardening downgrade is intentionally unsupported. Restore the "
        "verified pre-migration database snapshot instead of weakening immutable evidence."
    )
