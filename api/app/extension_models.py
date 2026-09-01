from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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


class ExtensionCase(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("workspace_id", "case_number", name="uq_extension_case_number"),
        CheckConstraint(
            "status IN ('NEW','ASSIGNED','IN_OBSERVATION','IN_VERIFICATION',"
            "'ACTION_PLANNED','FOLLOW_UP','CLOSED','CANCELLED')",
            name="ck_extension_case_status",
        ),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_number: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    crop: Mapped[str] = mapped_column(String(120), default="Rice")
    growth_stage: Mapped[str] = mapped_column(String(120), default="Not recorded")
    severity: Mapped[str] = mapped_column(String(32), default="MODERATE")
    affected_area_ha: Mapped[float | None] = mapped_column(Float)
    location_label: Mapped[str] = mapped_column(String(240), default="Approximate demo location")
    approximate_lat: Mapped[float | None] = mapped_column(Float)
    approximate_lon: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(32), default="NORMAL", index=True)
    status: Mapped[str] = mapped_column(String(32), default="NEW", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    assessment_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    demonstration: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    current_assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    last_observation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action: Mapped[str] = mapped_column(String(300), default="Await assignment")
    sync_status: Mapped[str] = mapped_column(String(32), default="SYNCED")
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseAssignment(Base):
    __tablename__ = "case_assignments"
    __table_args__ = ({"schema": "extension"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.cases.id", ondelete="RESTRICT"), index=True)
    officer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "client_uuid", name="uq_extension_observation_client"),
        CheckConstraint("status IN ('DRAFT','COMPLETED')", name="ck_extension_observation_status"),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.cases.id", ondelete="RESTRICT"), index=True)
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="MODERATE")
    affected_area_ha: Mapped[float | None] = mapped_column(Float)
    approximate_location: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    structured_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = ({"schema": "extension"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.cases.id", ondelete="RESTRICT"), index=True)
    observation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extension.observations.id", ondelete="RESTRICT"), index=True)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    thumbnail_object_key: Mapped[str | None] = mapped_column(String(1000))
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    exif_stripped: Mapped[bool] = mapped_column(Boolean, default=False)
    classification: Mapped[str] = mapped_column(String(32), default="SENSITIVE_FIELD")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    __table_args__ = (
        UniqueConstraint("workspace_id", "item_key", name="uq_extension_knowledge_key"),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    demonstration: Mapped[bool] = mapped_column(Boolean, default=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("knowledge_item_id", "version_number", name="uq_extension_knowledge_version"),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    knowledge_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.knowledge_items.id", ondelete="RESTRICT"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    source_summary: Mapped[str] = mapped_column(Text, default="Placeholder source metadata for demonstration only.")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = ({"schema": "extension"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    knowledge_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.knowledge_versions.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    citation: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(String(1000))
    placeholder: Mapped[bool] = mapped_column(Boolean, default=True)


class VerificationTemplateVersion(Base):
    __tablename__ = "verification_template_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "template_key", "version_number", name="uq_extension_template_version"),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    template_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DEMO_APPROVED")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VerificationItem(Base):
    __tablename__ = "verification_items"
    __table_args__ = (
        UniqueConstraint("template_version_id", "ordinal", name="uq_extension_verification_item_order"),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    template_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.verification_template_versions.id", ondelete="RESTRICT"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response_type: Mapped[str] = mapped_column(String(64), default="YES_NO_UNKNOWN")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    required_evidence: Mapped[str] = mapped_column(Text, default="")


class VerificationSession(Base):
    __tablename__ = "verification_sessions"
    __table_args__ = (
        UniqueConstraint("case_id", "revision_number", name="uq_extension_verification_revision"),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.cases.id", ondelete="RESTRICT"), index=True)
    template_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.verification_template_versions.id", ondelete="RESTRICT"))
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VerificationResponse(Base):
    __tablename__ = "verification_responses"
    __table_args__ = (
        UniqueConstraint("verification_session_id", "verification_item_id", name="uq_extension_verification_response"),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    verification_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.verification_sessions.id", ondelete="RESTRICT"), index=True)
    verification_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.verification_items.id", ondelete="RESTRICT"))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_note: Mapped[str] = mapped_column(Text, default="")


class ActivityPlan(Base):
    __tablename__ = "activity_plans"
    __table_args__ = ({"schema": "extension"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extension.cases.id", ondelete="RESTRICT"), index=True)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    participant_count: Mapped[int] = mapped_column(Integer, default=0)
    responsible_officer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    outcome: Mapped[str] = mapped_column(Text, default="")
    closure_evidence: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityStep(Base):
    __tablename__ = "activity_steps"
    __table_args__ = (
        UniqueConstraint("activity_plan_id", "ordinal", name="uq_extension_activity_step_order"),
        {"schema": "extension"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    activity_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.activity_plans.id", ondelete="RESTRICT"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    responsible_officer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    due_date: Mapped[date | None] = mapped_column(Date)


class FollowUp(Base):
    __tablename__ = "follow_ups"
    __table_args__ = ({"schema": "extension"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.cases.id", ondelete="RESTRICT"), index=True)
    activity_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extension.activity_plans.id", ondelete="RESTRICT"))
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)


class CaseStatusHistory(Base):
    __tablename__ = "case_status_history"
    __table_args__ = ({"schema": "extension"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.cases.id", ondelete="RESTRICT"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssessmentCandidate(Base):
    __tablename__ = "assessment_candidates"
    __table_args__ = ({"schema": "extension"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.cases.id", ondelete="RESTRICT"), index=True)
    knowledge_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extension.knowledge_versions.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(32), default="PROPOSED")
    supporting_observation_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    missing_information: Mapped[list[str]] = mapped_column(JSONB, default=list)
    selected_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    review_reason: Mapped[str] = mapped_column(Text, default="")
    row_version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
