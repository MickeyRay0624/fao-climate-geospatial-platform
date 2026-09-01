"""Harden exact-version collections for the demonstration platform.

Revision ID: 20260901_0004
Revises: 20260831_0003
"""

from alembic import op


revision = "20260901_0004"
down_revision = "20260831_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE catalog.collections
          ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb,
          ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
          ADD COLUMN IF NOT EXISTS row_version BIGINT NOT NULL DEFAULT 1,
          ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
        CREATE INDEX IF NOT EXISTS ix_catalog_collections_status
          ON catalog.collections (status);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_collection_exact_version_idx
          ON catalog.collection_members (collection_id, dataset_version_id)
          WHERE dataset_version_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Collection hardening downgrade is intentionally unsupported. "
        "Restore a verified database backup instead of removing governed records."
    )
