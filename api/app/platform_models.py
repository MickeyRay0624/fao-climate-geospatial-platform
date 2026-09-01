from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def uuid4() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "external_subject", name="uq_user_external_identity"),
        {"schema": "iam"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    locale: Mapped[str] = mapped_column(String(16), default="en")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = ({"schema": "core"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_workspace_org_slug"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    country_codes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    default_visibility: Mapped[str] = mapped_column(String(32), default="PRIVATE")
    default_classification: Mapped[str] = mapped_column(String(32), default="FAO_INTERNAL")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("iam.users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_group_workspace_slug"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.workspaces.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_membership"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("iam.users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Module(Base):
    __tablename__ = "modules"
    __table_args__ = ({"schema": "core"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    module_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    module_version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="installed")
    manifest_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceModule(Base):
    __tablename__ = "workspace_modules"
    __table_args__ = (
        UniqueConstraint("workspace_id", "module_id", name="uq_workspace_module"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.workspaces.id", ondelete="CASCADE"), index=True)
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.modules.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_flags: Mapped[dict[str, bool]] = mapped_column(JSONB, default=dict)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = ({"schema": "governance"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "role_key", name="uq_role_workspace_key"),
        {"schema": "governance"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    role_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    system_role: Mapped[bool] = mapped_column(Boolean, default=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
        {"schema": "governance"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("governance.roles.id", ondelete="CASCADE"), index=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("governance.permissions.id", ondelete="CASCADE"), index=True)


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = ({"schema": "governance"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("governance.roles.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(32), default="workspace")
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text, default="Seeded development role")


class PermissionGrant(Base):
    __tablename__ = "permission_grants"
    __table_args__ = (
        CheckConstraint("effect IN ('ALLOW','DENY')", name="ck_permission_grant_effect"),
        {"schema": "governance"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    permission_code: Mapped[str] = mapped_column(String(160), nullable=False)
    effect: Mapped[str] = mapped_column(String(8), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogDataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_catalog_dataset_workspace_slug"),
        CheckConstraint(
            "NOT (classification = 'SENSITIVE_FIELD' AND visibility = 'PUBLIC')",
            name="ck_dataset_sensitive_not_public",
        ),
        CheckConstraint(
            "visibility IN ('PRIVATE','RESTRICTED','WORKSPACE','TEAM','FAO_INTERNAL','PUBLIC')",
            name="ck_catalog_dataset_visibility",
        ),
        CheckConstraint(
            "classification IN ('PUBLIC','FAO_INTERNAL','RESTRICTED','SENSITIVE_FIELD')",
            name="ck_catalog_dataset_classification",
        ),
        CheckConstraint(
            "lifecycle_status IN ('ACTIVE','ARCHIVED')",
            name="ck_catalog_dataset_lifecycle",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    abstract: Mapped[str] = mapped_column(Text, default="")
    data_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    steward_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    visibility: Mapped[str] = mapped_column(String(32), default="PRIVATE", index=True)
    classification: Mapped[str] = mapped_column(String(32), default="FAO_INTERNAL", index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    current_published_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    default_quality_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    licence_code: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CatalogDatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_label", name="uq_catalog_dataset_version"),
        CheckConstraint(
            "state IN ('DRAFT','UPLOADING','PROCESSING','VALIDATION_FAILED','VALIDATED',"
            "'IN_REVIEW','CHANGES_REQUESTED','APPROVED','PUBLISHED','DEPRECATED','ARCHIVED')",
            name="ck_catalog_dataset_version_state",
        ),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.datasets.id", ondelete="RESTRICT"), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    profile_key: Mapped[str] = mapped_column(String(160), nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, default="")
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CatalogAsset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "sha256", "role", name="uq_catalog_asset_content_role"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.dataset_versions.id", ondelete="RESTRICT"), index=True)
    role: Mapped[str] = mapped_column(String(64), default="source")
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    upload_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    scan_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    storage_class: Mapped[str] = mapped_column(String(32), default="STANDARD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Representation(Base):
    __tablename__ = "representations"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.dataset_versions.id", ondelete="RESTRICT"), index=True)
    representation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    locator: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="READY")
    crs: Mapped[str | None] = mapped_column(String(80))
    geometry_type: Mapped[str | None] = mapped_column(String(80))
    bbox_json: Mapped[list[float] | None] = mapped_column(JSONB)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    statistics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    preview_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetadataRecord(Base):
    __tablename__ = "metadata_records"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.dataset_versions.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    abstract: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, default="")
    producer: Mapped[str] = mapped_column(String(300), default="")
    provenance: Mapped[str] = mapped_column(Text, default="")
    licence_code: Mapped[str | None] = mapped_column(String(120))
    use_limitation: Mapped[str] = mapped_column(Text, default="")
    crs: Mapped[str | None] = mapped_column(String(80))
    methodology: Mapped[str] = mapped_column(Text, default="")
    quality_statement: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    language: Mapped[str] = mapped_column(String(16), default="en")
    sensitive_data_declaration: Mapped[str] = mapped_column(Text, default="None declared")
    citation: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetadataContact(Base):
    __tablename__ = "metadata_contacts"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    metadata_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.metadata_records.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    organization_name: Mapped[str | None] = mapped_column(String(300))


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_collection_workspace_slug"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionMember(Base):
    __tablename__ = "collection_members"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.collections.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(String(80), default="member")
    ordinal: Mapped[int] = mapped_column(Integer, default=0)


class QualityProfile(Base):
    __tablename__ = "quality_profiles"
    __table_args__ = (
        UniqueConstraint("profile_key", "profile_version", name="uq_quality_profile_version"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_key: Mapped[str] = mapped_column(String(160), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False)
    data_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class QualityRun(Base):
    __tablename__ = "quality_runs"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.dataset_versions.id", ondelete="RESTRICT"), index=True)
    quality_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.quality_profiles.id", ondelete="RESTRICT"))
    engine_version: Mapped[str] = mapped_column(String(64), default="platform-validator/1.0")
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class QualityIssue(Base):
    __tablename__ = "quality_issues"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    quality_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.quality_runs.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    affected_count: Mapped[int] = mapped_column(Integer, default=0)
    location_ref: Mapped[str | None] = mapped_column(String(500))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    resolution_status: Mapped[str] = mapped_column(String(32), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewRequest(Base):
    __tablename__ = "review_requests"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.dataset_versions.id", ondelete="RESTRICT"), index=True)
    review_type: Mapped[str] = mapped_column(String(32), default="publication")
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewer_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    review_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.review_requests.id", ondelete="RESTRICT"), index=True)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    checklist_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    exception_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LineageProcess(Base):
    __tablename__ = "lineage_processes"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    process_type: Mapped[str] = mapped_column(String(64), nullable=False)
    module_key: Mapped[str] = mapped_column(String(120), default="data-hub")
    external_run_type: Mapped[str | None] = mapped_column(String(120))
    external_run_id: Mapped[str | None] = mapped_column(String(240))
    method_identifier: Mapped[str | None] = mapped_column(String(200))
    method_version: Mapped[str | None] = mapped_column(String(64))
    code_ref: Mapped[str | None] = mapped_column(String(240))
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="SUCCEEDED")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LineageEdge(Base):
    __tablename__ = "lineage_edges"
    __table_args__ = ({"schema": "catalog"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    process_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.lineage_processes.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog.dataset_versions.id", ondelete="RESTRICT"), index=True)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = ({"schema": "jobs"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadSessionFile(Base):
    __tablename__ = "upload_session_files"
    __table_args__ = ({"schema": "jobs"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    upload_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.upload_sessions.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(String(64))
    quarantine_object_key: Mapped[str] = mapped_column(String(1000), unique=True)
    uploaded_size: Mapped[int | None] = mapped_column(BigInteger)
    etag: Mapped[str | None] = mapped_column(String(160))


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = ({"schema": "jobs"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    job_type: Mapped[str] = mapped_column(String(160), nullable=False)
    module_key: Mapped[str] = mapped_column(String(120), default="data-hub")
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_code: Mapped[str | None] = mapped_column(String(160))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobStep(Base):
    __tablename__ = "job_steps"
    __table_args__ = (
        UniqueConstraint("job_id", "ordinal", name="uq_job_step_ordinal"),
        {"schema": "jobs"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.processing_jobs.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "events"
    __table_args__ = ({"schema": "audit"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor_type: Mapped[str] = mapped_column(String(32), default="user")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    severity: Mapped[str] = mapped_column(String(32), default="INFO")


class LegacyIdMapping(Base):
    __tablename__ = "legacy_id_mappings"
    __table_args__ = (
        UniqueConstraint("entity_type", "legacy_id", name="uq_legacy_mapping"),
        {"schema": "integration"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    legacy_id: Mapped[str] = mapped_column(String(120), nullable=False)
    new_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", "method", "path", name="uq_idempotency_request"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
