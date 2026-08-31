"""Create the governed native investment domain and database guards.

Revision ID: 20260831_0003
Revises: 20260831_0002
"""

from alembic import op


revision = "20260831_0003"
down_revision = "20260831_0002"
branch_labels = None
depends_on = None


INVESTMENT_TABLES = (
    "investment.indicator_definitions",
    "investment.method_definitions",
    "investment.method_versions",
    "investment.scenarios",
    "investment.scenario_parameters",
    "investment.analysis_input_sets",
    "investment.analysis_input_members",
    "investment.analysis_runs",
    "investment.analysis_run_inputs",
    "investment.priority_results",
    "investment.run_comparisons",
)


def upgrade() -> None:
    bind = op.get_bind()
    from app.models import Base
    import app.platform_models  # noqa: F401

    # Revision 0001 intentionally loads current metadata for a clean bootstrap.
    # checkfirst therefore makes this revision converge both a preserved Phase 1
    # database and a database created from base with the current source tree.
    for table_name in INVESTMENT_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)

    # Existing published compatibility bundles predate representations. This is
    # a one-time metadata reconciliation only: the original object and version
    # remain untouched. Future backfills create the row before publication.
    op.execute(
        """
        ALTER TABLE catalog.representations DISABLE TRIGGER protect_published_representation;
        INSERT INTO catalog.representations (
          id, dataset_version_id, representation_type, locator, status, crs,
          geometry_type, schema_json, statistics_json, preview_json, created_at
        )
        SELECT
          (
            substr(md5('investment-legacy-representation:' || v.id::text), 1, 8) || '-' ||
            substr(md5('investment-legacy-representation:' || v.id::text), 9, 4) || '-' ||
            substr(md5('investment-legacy-representation:' || v.id::text), 13, 4) || '-' ||
            substr(md5('investment-legacy-representation:' || v.id::text), 17, 4) || '-' ||
            substr(md5('investment-legacy-representation:' || v.id::text), 21, 12)
          )::uuid,
          v.id,
          'legacy_priority_bundle',
          a.object_key,
          'READY',
          'EPSG:4326',
          'MultiPolygon',
          jsonb_build_object(
            'profile', 'analysis-ready-priority-bundle@1.0',
            'area_code_field', 'code',
            'geometry_field', 'geometry',
            'indicator_fields', jsonb_build_array(
              'yield_gap','drought_risk','flood_risk','poverty_index',
              'irrigation_gap','market_isolation','nbs_opportunity'
            )
          ),
          jsonb_build_object('record_count', coalesce((v.metadata_snapshot->>'record_count')::int, 111)),
          NULL,
          now()
        FROM catalog.dataset_versions v
        JOIN LATERAL (
          SELECT object_key FROM catalog.assets
          WHERE dataset_version_id = v.id AND role = 'source'
          ORDER BY created_at LIMIT 1
        ) a ON true
        WHERE v.profile_key = 'analysis-ready-priority-bundle@1.0'
          AND NOT EXISTS (
            SELECT 1 FROM catalog.representations r
            WHERE r.dataset_version_id = v.id
              AND r.representation_type = 'legacy_priority_bundle'
          );
        ALTER TABLE catalog.representations ENABLE TRIGGER protect_published_representation;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION investment.protect_method_version() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND OLD.state IN ('APPROVED','RETIRED') THEN
            RAISE EXCEPTION 'approved method versions are immutable' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'UPDATE' THEN
            IF OLD.state IN ('APPROVED','RETIRED') AND (
              NEW.method_id IS DISTINCT FROM OLD.method_id OR
              NEW.version_label IS DISTINCT FROM OLD.version_label OR
              NEW.specification_json IS DISTINCT FROM OLD.specification_json OR
              NEW.checksum IS DISTINCT FROM OLD.checksum OR
              NEW.implementation_key IS DISTINCT FROM OLD.implementation_key OR
              NEW.code_ref IS DISTINCT FROM OLD.code_ref OR
              NEW.container_metadata IS DISTINCT FROM OLD.container_metadata OR
              NEW.validation_evidence IS DISTINCT FROM OLD.validation_evidence OR
              NEW.disclaimer IS DISTINCT FROM OLD.disclaimer OR
              NEW.created_by IS DISTINCT FROM OLD.created_by OR
              NEW.approved_by IS DISTINCT FROM OLD.approved_by OR
              NEW.approved_at IS DISTINCT FROM OLD.approved_at OR
              (OLD.state = 'RETIRED' AND NEW.state <> 'RETIRED') OR
              (OLD.state = 'APPROVED' AND NEW.state NOT IN ('APPROVED','RETIRED'))
            ) THEN
              RAISE EXCEPTION 'approved method versions are immutable' USING ERRCODE = '55000';
            END IF;
            NEW.row_version := OLD.row_version + 1;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_method_version ON investment.method_versions;
        CREATE TRIGGER protect_method_version
          BEFORE UPDATE OR DELETE ON investment.method_versions
          FOR EACH ROW EXECUTE FUNCTION investment.protect_method_version();

        CREATE OR REPLACE FUNCTION investment.protect_scenario() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND OLD.state IN ('APPROVED','RETIRED') THEN
            RAISE EXCEPTION 'approved scenarios are immutable' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'UPDATE' THEN
            IF OLD.state IN ('APPROVED','RETIRED') AND (
              NEW.workspace_id IS DISTINCT FROM OLD.workspace_id OR
              NEW.scenario_key IS DISTINCT FROM OLD.scenario_key OR
              NEW.version_label IS DISTINCT FROM OLD.version_label OR
              NEW.name IS DISTINCT FROM OLD.name OR
              NEW.description IS DISTINCT FROM OLD.description OR
              NEW.method_version_id IS DISTINCT FROM OLD.method_version_id OR
              NEW.parameters_json IS DISTINCT FROM OLD.parameters_json OR
              NEW.checksum IS DISTINCT FROM OLD.checksum OR
              NEW.disclaimer IS DISTINCT FROM OLD.disclaimer OR
              NEW.created_by IS DISTINCT FROM OLD.created_by OR
              NEW.approved_by IS DISTINCT FROM OLD.approved_by OR
              NEW.approved_at IS DISTINCT FROM OLD.approved_at OR
              (OLD.state = 'RETIRED' AND NEW.state <> 'RETIRED') OR
              (OLD.state = 'APPROVED' AND NEW.state NOT IN ('APPROVED','RETIRED'))
            ) THEN
              RAISE EXCEPTION 'approved scenarios are immutable' USING ERRCODE = '55000';
            END IF;
            NEW.row_version := OLD.row_version + 1;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_scenario ON investment.scenarios;
        CREATE TRIGGER protect_scenario
          BEFORE UPDATE OR DELETE ON investment.scenarios
          FOR EACH ROW EXECUTE FUNCTION investment.protect_scenario();

        CREATE OR REPLACE FUNCTION investment.protect_scenario_parameter() RETURNS trigger AS $$
        DECLARE governed boolean; old_parent uuid; new_parent uuid;
        BEGIN
          IF TG_OP <> 'INSERT' THEN old_parent := OLD.scenario_id; END IF;
          IF TG_OP <> 'DELETE' THEN new_parent := NEW.scenario_id; END IF;
          SELECT EXISTS (
            SELECT 1 FROM investment.scenarios
            WHERE id IN (old_parent, new_parent)
              AND state IN ('APPROVED','RETIRED')
          ) INTO governed;
          IF governed THEN
            RAISE EXCEPTION 'parameters of approved scenarios are immutable' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_scenario_parameter ON investment.scenario_parameters;
        CREATE TRIGGER protect_scenario_parameter
          BEFORE INSERT OR UPDATE OR DELETE ON investment.scenario_parameters
          FOR EACH ROW EXECUTE FUNCTION investment.protect_scenario_parameter();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION investment.protect_input_set() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND OLD.status IN ('LOCKED','RETIRED') THEN
            RAISE EXCEPTION 'locked input sets are immutable' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'UPDATE' THEN
            IF OLD.status IN ('LOCKED','RETIRED') AND (
              NEW.workspace_id IS DISTINCT FROM OLD.workspace_id OR
              NEW.name IS DISTINCT FROM OLD.name OR
              NEW.label IS DISTINCT FROM OLD.label OR
              NEW.profile_mode IS DISTINCT FROM OLD.profile_mode OR
              NEW.study_area_ref IS DISTINCT FROM OLD.study_area_ref OR
              NEW.run_mode_compatibility IS DISTINCT FROM OLD.run_mode_compatibility OR
              NEW.strictest_classification IS DISTINCT FROM OLD.strictest_classification OR
              NEW.readiness_result IS DISTINCT FROM OLD.readiness_result OR
              NEW.warnings_json IS DISTINCT FROM OLD.warnings_json OR
              NEW.checksum IS DISTINCT FROM OLD.checksum OR
              NEW.created_by IS DISTINCT FROM OLD.created_by OR
              NEW.locked_by IS DISTINCT FROM OLD.locked_by OR
              NEW.locked_at IS DISTINCT FROM OLD.locked_at OR
              (OLD.status = 'RETIRED' AND NEW.status <> 'RETIRED') OR
              (OLD.status = 'LOCKED' AND NEW.status NOT IN ('LOCKED','RETIRED'))
            ) THEN
              RAISE EXCEPTION 'locked input sets are immutable' USING ERRCODE = '55000';
            END IF;
            NEW.row_version := OLD.row_version + 1;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_input_set ON investment.analysis_input_sets;
        CREATE TRIGGER protect_input_set
          BEFORE UPDATE OR DELETE ON investment.analysis_input_sets
          FOR EACH ROW EXECUTE FUNCTION investment.protect_input_set();

        CREATE OR REPLACE FUNCTION investment.protect_input_member() RETURNS trigger AS $$
        DECLARE governed boolean; old_parent uuid; new_parent uuid;
        BEGIN
          IF TG_OP <> 'INSERT' THEN old_parent := OLD.input_set_id; END IF;
          IF TG_OP <> 'DELETE' THEN new_parent := NEW.input_set_id; END IF;
          SELECT EXISTS (
            SELECT 1 FROM investment.analysis_input_sets
            WHERE id IN (old_parent, new_parent)
              AND status IN ('LOCKED','RETIRED')
          ) INTO governed;
          IF governed THEN
            RAISE EXCEPTION 'members of locked input sets are immutable' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_input_member ON investment.analysis_input_members;
        CREATE TRIGGER protect_input_member
          BEFORE INSERT OR UPDATE OR DELETE ON investment.analysis_input_members
          FOR EACH ROW EXECUTE FUNCTION investment.protect_input_member();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION investment.protect_completed_run() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND OLD.status IN ('succeeded','succeeded_with_warnings') THEN
            RAISE EXCEPTION 'successful investment runs are immutable' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'UPDATE' THEN
            IF OLD.status IN ('succeeded','succeeded_with_warnings') THEN
              RAISE EXCEPTION 'successful investment runs are immutable' USING ERRCODE = '55000';
            END IF;
            NEW.row_version := OLD.row_version + 1;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_completed_run ON investment.analysis_runs;
        CREATE TRIGGER protect_completed_run
          BEFORE UPDATE OR DELETE ON investment.analysis_runs
          FOR EACH ROW EXECUTE FUNCTION investment.protect_completed_run();

        CREATE OR REPLACE FUNCTION investment.protect_run_input() RETURNS trigger AS $$
        DECLARE frozen boolean; old_parent uuid; new_parent uuid;
        BEGIN
          IF TG_OP <> 'INSERT' THEN old_parent := OLD.run_id; END IF;
          IF TG_OP <> 'DELETE' THEN new_parent := NEW.run_id; END IF;
          SELECT EXISTS (
            SELECT 1 FROM investment.analysis_runs
            WHERE id IN (old_parent, new_parent)
              AND status <> 'queued'
          ) INTO frozen;
          IF frozen THEN
            RAISE EXCEPTION 'analysis run input snapshots are immutable after queueing' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_run_input ON investment.analysis_run_inputs;
        CREATE TRIGGER protect_run_input
          BEFORE INSERT OR UPDATE OR DELETE ON investment.analysis_run_inputs
          FOR EACH ROW EXECUTE FUNCTION investment.protect_run_input();

        CREATE OR REPLACE FUNCTION investment.protect_priority_result() RETURNS trigger AS $$
        DECLARE frozen boolean; old_parent uuid; new_parent uuid;
        BEGIN
          IF TG_OP <> 'INSERT' THEN old_parent := OLD.run_id; END IF;
          IF TG_OP <> 'DELETE' THEN new_parent := NEW.run_id; END IF;
          SELECT EXISTS (
            SELECT 1 FROM investment.analysis_runs
            WHERE id IN (old_parent, new_parent)
              AND status IN ('succeeded','succeeded_with_warnings')
          ) INTO frozen;
          IF frozen THEN
            RAISE EXCEPTION 'results of successful investment runs are immutable' USING ERRCODE = '55000';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS protect_priority_result ON investment.priority_results;
        CREATE TRIGGER protect_priority_result
          BEFORE INSERT OR UPDATE OR DELETE ON investment.priority_results
          FOR EACH ROW EXECUTE FUNCTION investment.protect_priority_result();
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Investment native migration downgrade is intentionally unsupported. "
        "Restore the verified pre-Phase-2A PostgreSQL dump and matching object inventory."
    )
