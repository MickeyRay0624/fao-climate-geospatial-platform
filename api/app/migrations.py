from __future__ import annotations

from sqlalchemy import text

from app.database import engine
from app.models import Base


def ensure_schema() -> None:
    """Apply the small idempotent MVP migration set.

    The first version of this demonstrator pre-dated dataset versioning. These
    statements preserve the existing local volume while adding the new catalogue
    foreign keys and allowing the same commune code in different versions.
    """

    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

    Base.metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE admin_areas "
                "ADD COLUMN IF NOT EXISTS dataset_version_id INTEGER"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE analysis_runs "
                "ADD COLUMN IF NOT EXISTS dataset_version_id INTEGER"
            )
        )
        connection.execute(text("DROP INDEX IF EXISTS ix_admin_areas_code"))
        connection.execute(
            text("ALTER TABLE admin_areas DROP CONSTRAINT IF EXISTS admin_areas_code_key")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_admin_areas_code ON admin_areas (code)")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_admin_areas_dataset_version_id "
                "ON admin_areas (dataset_version_id)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_version_area_code_idx "
                "ON admin_areas (dataset_version_id, code) "
                "WHERE dataset_version_id IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_analysis_runs_dataset_version_id "
                "ON analysis_runs (dataset_version_id)"
            )
        )
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_admin_areas_dataset_version'
                  ) THEN
                    ALTER TABLE admin_areas
                    ADD CONSTRAINT fk_admin_areas_dataset_version
                    FOREIGN KEY (dataset_version_id)
                    REFERENCES data_versions(id)
                    ON DELETE CASCADE;
                  END IF;
                END $$
                """
            )
        )
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_analysis_runs_dataset_version'
                  ) THEN
                    ALTER TABLE analysis_runs
                    ADD CONSTRAINT fk_analysis_runs_dataset_version
                    FOREIGN KEY (dataset_version_id)
                    REFERENCES data_versions(id)
                    ON DELETE RESTRICT;
                  END IF;
                END $$
                """
            )
        )

