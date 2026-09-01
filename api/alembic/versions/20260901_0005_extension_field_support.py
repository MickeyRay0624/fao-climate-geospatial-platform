"""Create the isolated Extension Field Support workflow domain.

Revision ID: 20260901_0005
Revises: 20260901_0004
"""

from alembic import op


revision = "20260901_0005"
down_revision = "20260901_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS extension")

    # Import the extension metadata only when this revision is actually being
    # applied. Alembic imports every revision module before it runs the chain;
    # a module-level import would make the baseline migration see these tables
    # before the extension schema exists on a clean database.
    from app.models import Base
    import app.extension_models  # noqa: F401 - registers extension metadata

    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.schema == "extension":
            table.create(bind=bind, checkfirst=True)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION extension.reject_append_only_change()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'extension history is append-only';
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_extension_case_history_append_only
          ON extension.case_status_history;
        CREATE TRIGGER trg_extension_case_history_append_only
          BEFORE UPDATE OR DELETE ON extension.case_status_history
          FOR EACH ROW EXECUTE FUNCTION extension.reject_append_only_change();

        CREATE OR REPLACE FUNCTION extension.protect_completed_record()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status = 'COMPLETED' THEN
            RAISE EXCEPTION 'completed extension records are immutable';
          END IF;
          RETURN NEW;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_extension_observation_immutable
          ON extension.observations;
        CREATE TRIGGER trg_extension_observation_immutable
          BEFORE UPDATE OR DELETE ON extension.observations
          FOR EACH ROW EXECUTE FUNCTION extension.protect_completed_record();

        DROP TRIGGER IF EXISTS trg_extension_verification_immutable
          ON extension.verification_sessions;
        CREATE TRIGGER trg_extension_verification_immutable
          BEFORE UPDATE OR DELETE ON extension.verification_sessions
          FOR EACH ROW EXECUTE FUNCTION extension.protect_completed_record();

        CREATE OR REPLACE FUNCTION extension.protect_completed_verification_response()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target_session UUID;
        BEGIN
          target_session := CASE WHEN TG_OP = 'DELETE'
            THEN OLD.verification_session_id ELSE NEW.verification_session_id END;
          IF EXISTS (
            SELECT 1 FROM extension.verification_sessions
            WHERE id = target_session AND status = 'COMPLETED'
          ) THEN
            RAISE EXCEPTION 'completed verification responses are immutable';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_extension_response_immutable
          ON extension.verification_responses;
        CREATE TRIGGER trg_extension_response_immutable
          BEFORE INSERT OR UPDATE OR DELETE ON extension.verification_responses
          FOR EACH ROW EXECUTE FUNCTION extension.protect_completed_verification_response();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Extension workflow downgrade is intentionally unsupported. Restore a "
        "verified database backup instead of deleting governed field records."
    )
