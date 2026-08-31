"""Create the platform foundation alongside the legacy DSS schema.

Revision ID: 20260831_0001
Revises: None
"""

from alembic import op


revision = "20260831_0001"
down_revision = None
branch_labels = None
depends_on = None


SCHEMAS = ("iam", "core", "governance", "catalog", "jobs", "audit", "integration", "investment")


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # This is the baseline migration for a previously unversioned demonstrator.
    # checkfirst=True makes it safe for both the preserved legacy database and a
    # clean bootstrap while Alembic owns every subsequent schema change.
    from app.models import Base
    import app.platform_models  # noqa: F401

    Base.metadata.create_all(bind=bind, checkfirst=True)

    op.execute("ALTER TABLE admin_areas ADD COLUMN IF NOT EXISTS catalog_version_id UUID")
    op.execute("ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS catalog_version_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_areas_catalog_version_id "
        "ON admin_areas (catalog_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analysis_runs_catalog_version_id "
        "ON analysis_runs (catalog_version_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_version_area_code_idx "
        "ON admin_areas (catalog_version_id, code) WHERE catalog_version_id IS NOT NULL"
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_admin_area_catalog_version') THEN
            ALTER TABLE admin_areas ADD CONSTRAINT fk_admin_area_catalog_version
            FOREIGN KEY (catalog_version_id) REFERENCES catalog.dataset_versions(id) ON DELETE RESTRICT;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_analysis_run_catalog_version') THEN
            ALTER TABLE analysis_runs ADD CONSTRAINT fk_analysis_run_catalog_version
            FOREIGN KEY (catalog_version_id) REFERENCES catalog.dataset_versions(id) ON DELETE RESTRICT;
          END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit.reject_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit.events is append-only' USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS audit_events_append_only ON audit.events;
        CREATE TRIGGER audit_events_append_only
          BEFORE UPDATE OR DELETE ON audit.events
          FOR EACH ROW EXECUTE FUNCTION audit.reject_event_mutation();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION catalog.protect_published_version() RETURNS trigger AS $$
        BEGIN
          IF OLD.state IN ('PUBLISHED','DEPRECATED','ARCHIVED') THEN
            IF NEW.version_label IS DISTINCT FROM OLD.version_label
               OR NEW.profile_key IS DISTINCT FROM OLD.profile_key
               OR NEW.change_summary IS DISTINCT FROM OLD.change_summary
               OR NEW.supersedes_version_id IS DISTINCT FROM OLD.supersedes_version_id
               OR NEW.metadata_snapshot IS DISTINCT FROM OLD.metadata_snapshot
               OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
              RAISE EXCEPTION 'published dataset versions are immutable' USING ERRCODE = '55000';
            END IF;
            IF OLD.state = 'PUBLISHED' AND NEW.state NOT IN ('PUBLISHED','DEPRECATED') THEN
              RAISE EXCEPTION 'invalid published version transition' USING ERRCODE = '55000';
            END IF;
            IF OLD.state = 'DEPRECATED' AND NEW.state NOT IN ('DEPRECATED','ARCHIVED') THEN
              RAISE EXCEPTION 'invalid deprecated version transition' USING ERRCODE = '55000';
            END IF;
            IF OLD.state = 'ARCHIVED' AND NEW.state <> 'ARCHIVED' THEN
              RAISE EXCEPTION 'archived version is immutable' USING ERRCODE = '55000';
            END IF;
          END IF;
          NEW.row_version := OLD.row_version + 1;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS protect_published_version ON catalog.dataset_versions;
        CREATE TRIGGER protect_published_version
          BEFORE UPDATE ON catalog.dataset_versions
          FOR EACH ROW EXECUTE FUNCTION catalog.protect_published_version();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION catalog.protect_published_asset() RETURNS trigger AS $$
        DECLARE version_state text;
        BEGIN
          SELECT state INTO version_state FROM catalog.dataset_versions
          WHERE id = COALESCE(OLD.dataset_version_id, NEW.dataset_version_id);
          IF version_state IN ('PUBLISHED','DEPRECATED','ARCHIVED') THEN
            RAISE EXCEPTION 'assets and representations of published versions are immutable' USING ERRCODE = '55000';
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
          FOR EACH ROW EXECUTE FUNCTION catalog.protect_published_asset();
        DROP TRIGGER IF EXISTS protect_published_representation ON catalog.representations;
        CREATE TRIGGER protect_published_representation
          BEFORE INSERT OR UPDATE OR DELETE ON catalog.representations
          FOR EACH ROW EXECUTE FUNCTION catalog.protect_published_asset();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is intentionally unsupported: this revision backfills "
        "preserved legacy data into an authoritative catalog. Restore from the pre-migration backup."
    )
