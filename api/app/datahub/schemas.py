from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


Visibility = Literal["PRIVATE", "RESTRICTED", "WORKSPACE", "TEAM", "FAO_INTERNAL", "PUBLIC"]
Classification = Literal["PUBLIC", "FAO_INTERNAL", "RESTRICTED", "SENSITIVE_FIELD"]
DataKind = Literal["vector", "table", "document", "raster", "multidimensional", "model_output", "derived_product"]


class CreateDatasetRequest(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    slug: str | None = Field(default=None, max_length=160)
    abstract: str = Field(min_length=10)
    data_kind: DataKind
    visibility: Visibility = "PRIVATE"
    classification: Classification = "FAO_INTERNAL"
    licence_code: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def classification_ceiling(self):
        if self.classification == "SENSITIVE_FIELD" and self.visibility == "PUBLIC":
            raise ValueError("SENSITIVE_FIELD data cannot be PUBLIC")
        return self


class UpdateDatasetRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    abstract: str | None = Field(default=None, min_length=10)
    visibility: Visibility | None = None
    classification: Classification | None = None
    licence_code: str | None = Field(default=None, max_length=120)
    row_version: int = Field(ge=1)


class VersionMetadata(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    abstract: str = Field(min_length=10)
    purpose: str = ""
    producer: str = ""
    provenance: str = Field(min_length=5)
    licence_code: str | None = None
    use_limitation: str = Field(min_length=5)
    crs: str | None = None
    methodology: str = ""
    quality_statement: str = ""
    keywords: list[str] = Field(default_factory=list)
    language: str = "en"
    sensitive_data_declaration: str = "None declared"
    citation: str = ""
    source_url: str | None = None


class CreateVersionRequest(BaseModel):
    version_label: str = Field(min_length=1, max_length=120)
    profile_key: Literal[
        "analysis-ready-priority-bundle@1.0",
        "administrative-boundary@1.0",
        "normalised-indicator-layer@1.0",
        "generic-vector@1.0",
        "generic-table@1.0",
        "document@1.0",
    ]
    change_summary: str = ""
    supersedes_version_id: UUID | None = None
    metadata: VersionMetadata


class UpdateVersionRequest(BaseModel):
    change_summary: str | None = None
    metadata: VersionMetadata | None = None
    row_version: int = Field(ge=1)


class UploadFileSpec(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=3, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: str | None = None

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("filename must not contain a path")
        return value

    @field_validator("sha256")
    @classmethod
    def valid_sha(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value)):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return value.lower() if value else None


class CreateUploadSessionRequest(BaseModel):
    files: list[UploadFileSpec] = Field(min_length=1, max_length=20)


class SubmitReviewRequest(BaseModel):
    review_type: Literal["metadata", "technical", "domain", "publication"] = "publication"
    reviewer_group_id: UUID | None = None
    row_version: int = Field(ge=1)


class ReviewDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "CHANGES_REQUESTED", "REJECT"]
    rationale: str = Field(min_length=5)
    checklist_snapshot: dict[str, Any] = Field(default_factory=dict)
    exception_reason: str | None = None


class PublishRequest(BaseModel):
    row_version: int = Field(ge=1)
    exception_reason: str | None = None


class DeprecateRequest(BaseModel):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=5)


class CreateCollectionRequest(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    slug: str | None = Field(default=None, max_length=160)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)


class UpdateCollectionRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None, max_length=30)
    row_version: int = Field(ge=1)


class AddCollectionMemberRequest(BaseModel):
    dataset_version_id: UUID
    role: str = Field(default="member", min_length=1, max_length=80)
    ordinal: int = Field(default=0, ge=0, le=10000)


class ArchiveCollectionRequest(BaseModel):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=5, max_length=1000)


class CreateGrantRequest(BaseModel):
    subject_type: Literal["user", "group"]
    subject_id: UUID
    permission_code: Literal[
        "dataset.view_metadata", "dataset.preview", "dataset.download", "dataset.edit_metadata",
        "dataset.upload_version", "dataset.submit_review", "dataset.manage_access", "lineage.view"
    ]
    effect: Literal["ALLOW", "DENY"]
    expires_at: datetime | None = None
    reason: str = Field(min_length=5)

    @field_validator("expires_at")
    @classmethod
    def future_aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        if value <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return value
