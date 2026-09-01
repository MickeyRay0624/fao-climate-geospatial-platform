from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from shapely.geometry import mapping, shape

from app.audit_service import record_event
from app.authorization import assert_permission, require_dataset_access
from app.config import APP_ENV, MAX_DATA_HUB_UPLOAD_BYTES, PRESIGNED_URL_TTL_SECONDS
from app.database import get_session
from app.errors import PlatformError, conflict, not_found
from app.identity import Principal, get_current_principal
from app.jobs import process_upload_session
from app.object_store import get_bytes, presigned_get, presigned_put, stat_object
from app.platform_models import (
    CatalogAsset,
    CatalogDataset,
    CatalogDatasetVersion,
    Collection,
    CollectionMember,
    Group,
    IdempotencyRecord,
    LineageEdge,
    LineageProcess,
    MetadataRecord,
    PermissionGrant,
    ProcessingJob,
    QualityIssue,
    QualityRun,
    Representation,
    ReviewDecision,
    ReviewRequest,
    UploadSession,
    UploadSessionFile,
    User,
    WorkspaceMembership,
)
from app.datahub.schemas import (
    AddCollectionMemberRequest,
    ArchiveCollectionRequest,
    CreateCollectionRequest,
    CreateDatasetRequest,
    CreateGrantRequest,
    CreateUploadSessionRequest,
    CreateVersionRequest,
    DeprecateRequest,
    PublishRequest,
    ReviewDecisionRequest,
    SubmitReviewRequest,
    UpdateCollectionRequest,
    UpdateDatasetRequest,
    UpdateVersionRequest,
)


router = APIRouter(prefix="/api/data/v1", tags=["Data Hub"])


def now() -> datetime:
    return datetime.now(timezone.utc)


def correlation_id(request: Request) -> str:
    return request.state.correlation_id


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if not idempotency_key or len(idempotency_key) < 8:
        raise PlatformError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "Mutating Data Hub requests require an Idempotency-Key header of at least 8 characters.",
            400,
        )
    return idempotency_key[:255]


def _cached(
    session: Session, principal: Principal, key: str, method: str, path: str
) -> dict[str, Any] | None:
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == principal.user_id,
            IdempotencyRecord.idempotency_key == key,
            IdempotencyRecord.method == method,
            IdempotencyRecord.path == path,
        )
    )
    return row.response_json if row else None


def _remember(
    session: Session,
    principal: Principal,
    key: str,
    method: str,
    path: str,
    response: dict[str, Any],
    status: int = 200,
) -> None:
    session.add(
        IdempotencyRecord(
            actor_id=principal.user_id,
            idempotency_key=key,
            method=method,
            path=path,
            response_status=status,
            response_json=response,
        )
    )


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result or "dataset"


def _dataset_summary(session: Session, dataset: CatalogDataset) -> dict[str, Any]:
    owner = session.get(User, dataset.owner_user_id)
    current = session.get(CatalogDatasetVersion, dataset.current_published_version_id) if dataset.current_published_version_id else None
    version_count = session.scalar(
        select(func.count(CatalogDatasetVersion.id)).where(CatalogDatasetVersion.dataset_id == dataset.id)
    ) or 0
    latest_quality = None
    metadata = None
    representation = None
    if current:
        metadata = session.scalar(
            select(MetadataRecord).where(MetadataRecord.dataset_version_id == current.id)
        )
        representation = session.scalar(
            select(Representation)
            .where(
                Representation.dataset_version_id == current.id,
                Representation.status == "READY",
            )
            .order_by(Representation.created_at.desc())
            .limit(1)
        )
        latest_quality = session.scalar(
            select(QualityRun)
            .where(QualityRun.dataset_version_id == current.id)
            .order_by(QualityRun.completed_at.desc().nulls_last())
            .limit(1)
        )
    keywords = metadata.keywords if metadata else []
    real_sample = (
        dataset.licence_code == "UNCONFIRMED-SOURCE-LICENCE"
        or "real-data-test" in keywords
    )
    synthetic = dataset.licence_code == "DEMO-ONLY" or "synthetic" in keywords
    return {
        "id": str(dataset.id),
        "workspace_id": str(dataset.workspace_id),
        "slug": dataset.slug,
        "title": dataset.title,
        "abstract": dataset.abstract,
        "data_kind": dataset.data_kind,
        "owner": {"id": str(dataset.owner_user_id), "display_name": owner.display_name if owner else "Unknown"},
        "visibility": dataset.visibility,
        "classification": dataset.classification,
        "lifecycle_status": dataset.lifecycle_status,
        "licence_code": dataset.licence_code,
        "current_published_version": (
            {
                "id": str(current.id),
                "version_label": current.version_label,
                "state": current.state,
                "profile_key": current.profile_key,
            }
            if current else None
        ),
        "version_count": version_count,
        "quality_status": latest_quality.status if latest_quality else None,
        "tags": keywords,
        "evidence_type": "REAL_SAMPLE" if real_sample else "SYNTHETIC_DEMO" if synthetic else "GOVERNED",
        "licence_status": (
            "NOT_CONFIRMED"
            if dataset.licence_code == "UNCONFIRMED-SOURCE-LICENCE"
            else "DECLARED"
            if dataset.licence_code
            else "NOT_DECLARED"
        ),
        "spatial": (
            {
                "crs": representation.crs,
                "bbox": representation.bbox_json,
                "geometry_type": representation.geometry_type,
            }
            if representation
            else None
        ),
        "temporal": (
            {
                "start": representation.schema_json.get("time_start"),
                "end": representation.schema_json.get("time_end"),
            }
            if representation
            else None
        ),
        "row_version": dataset.row_version,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


def _version_payload(session: Session, version: CatalogDatasetVersion) -> dict[str, Any]:
    metadata = session.scalar(select(MetadataRecord).where(MetadataRecord.dataset_version_id == version.id))
    assets = session.scalars(
        select(CatalogAsset).where(CatalogAsset.dataset_version_id == version.id).order_by(CatalogAsset.created_at)
    ).all()
    representations = session.scalars(
        select(Representation).where(Representation.dataset_version_id == version.id).order_by(Representation.created_at)
    ).all()
    quality_runs = session.scalars(
        select(QualityRun).where(QualityRun.dataset_version_id == version.id).order_by(QualityRun.started_at.desc().nulls_last())
    ).all()
    latest_quality = quality_runs[0] if quality_runs else None
    issues = session.scalars(
        select(QualityIssue).where(QualityIssue.quality_run_id == latest_quality.id).order_by(QualityIssue.severity.desc(), QualityIssue.code)
    ).all() if latest_quality else []
    reviews = session.scalars(
        select(ReviewRequest).where(ReviewRequest.dataset_version_id == version.id).order_by(ReviewRequest.requested_at.desc())
    ).all()
    return {
        "id": str(version.id),
        "dataset_id": str(version.dataset_id),
        "version_label": version.version_label,
        "state": version.state,
        "profile_key": version.profile_key,
        "change_summary": version.change_summary,
        "supersedes_version_id": str(version.supersedes_version_id) if version.supersedes_version_id else None,
        "metadata": (
            {
                "title": metadata.title,
                "abstract": metadata.abstract,
                "purpose": metadata.purpose,
                "producer": metadata.producer,
                "provenance": metadata.provenance,
                "licence_code": metadata.licence_code,
                "use_limitation": metadata.use_limitation,
                "crs": metadata.crs,
                "methodology": metadata.methodology,
                "quality_statement": metadata.quality_statement,
                "keywords": metadata.keywords,
                "language": metadata.language,
                "sensitive_data_declaration": metadata.sensitive_data_declaration,
                "citation": metadata.citation,
                "source_url": metadata.source_url,
            } if metadata else None
        ),
        "metadata_snapshot": version.metadata_snapshot,
        "assets": [
            {
                "id": str(asset.id), "role": asset.role, "filename": asset.filename,
                "media_type": asset.media_type, "size_bytes": asset.size_bytes,
                "sha256": asset.sha256, "scan_status": asset.scan_status,
            }
            for asset in assets
        ],
        "representations": [
            {
                "id": str(item.id), "representation_type": item.representation_type,
                "status": item.status, "crs": item.crs, "geometry_type": item.geometry_type,
                "bbox": item.bbox_json, "schema": item.schema_json,
                "statistics": item.statistics_json, "preview": item.preview_json,
            }
            for item in representations
        ],
        "quality": (
            {
                "id": str(latest_quality.id), "status": latest_quality.status,
                "engine_version": latest_quality.engine_version, "summary": latest_quality.summary_json,
                "issues": [
                    {
                        "id": str(issue.id), "code": issue.code, "name": issue.name,
                        "severity": issue.severity, "affected_count": issue.affected_count,
                        "details": issue.details_json, "resolution_status": issue.resolution_status,
                    }
                    for issue in issues
                ],
            } if latest_quality else None
        ),
        "reviews": [
            {
                "id": str(review.id), "review_type": review.review_type,
                "status": review.status, "requested_by": str(review.requested_by),
                "requested_at": review.requested_at.isoformat(),
            }
            for review in reviews
        ],
        "created_by": str(version.created_by),
        "approved_by": str(version.approved_by) if version.approved_by else None,
        "published_by": str(version.published_by) if version.published_by else None,
        "row_version": version.row_version,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "submitted_at": version.submitted_at.isoformat() if version.submitted_at else None,
        "approved_at": version.approved_at.isoformat() if version.approved_at else None,
        "published_at": version.published_at.isoformat() if version.published_at else None,
    }


def _dataset_for_version(session: Session, version_id: UUID) -> tuple[CatalogDataset, CatalogDatasetVersion]:
    version = session.get(CatalogDatasetVersion, version_id)
    if version is None:
        raise not_found("Dataset version")
    dataset = session.get(CatalogDataset, version.dataset_id)
    if dataset is None:
        raise not_found("Dataset")
    return dataset, version


@router.get("/datasets")
def list_datasets(
    search: str | None = None,
    owner_id: UUID | None = None,
    data_kind: str | None = None,
    state: str | None = None,
    visibility: str | None = None,
    classification: str | None = None,
    quality: str | None = None,
    tag: str | None = None,
    mine: bool = False,
    scope: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: str = "-updated_at",
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "data.catalog.enter")
    query = select(CatalogDataset).where(
        CatalogDataset.workspace_id == principal.active_workspace_id,
        CatalogDataset.lifecycle_status != "ARCHIVED",
    )
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(CatalogDataset.title.ilike(term), CatalogDataset.abstract.ilike(term), CatalogDataset.slug.ilike(term)))
    if owner_id:
        query = query.where(CatalogDataset.owner_user_id == owner_id)
    if mine or scope == "owned":
        query = query.where(CatalogDataset.owner_user_id == principal.user_id)
    elif scope == "contributed":
        query = (
            query.join(
                CatalogDatasetVersion,
                CatalogDatasetVersion.dataset_id == CatalogDataset.id,
            )
            .where(CatalogDatasetVersion.created_by == principal.user_id)
            .distinct()
        )
    elif scope == "awaiting_action":
        query = (
            query.join(
                CatalogDatasetVersion,
                CatalogDatasetVersion.dataset_id == CatalogDataset.id,
            )
            .where(
                or_(
                    CatalogDataset.owner_user_id == principal.user_id,
                    CatalogDatasetVersion.created_by == principal.user_id,
                ),
                CatalogDatasetVersion.state.in_(
                    ["DRAFT", "VALIDATION_FAILED", "CHANGES_REQUESTED", "VALIDATED"]
                ),
            )
            .distinct()
        )
    elif scope == "shared":
        subjects = [principal.user_id, *principal.group_ids]
        shared_ids = select(PermissionGrant.resource_id).where(
            PermissionGrant.workspace_id == principal.active_workspace_id,
            PermissionGrant.resource_type.in_(["dataset", "dataset_version"]),
            PermissionGrant.subject_id.in_(subjects),
            PermissionGrant.effect == "ALLOW",
        )
        query = query.where(CatalogDataset.id.in_(shared_ids))
    if data_kind:
        query = query.where(CatalogDataset.data_kind == data_kind)
    if visibility:
        query = query.where(CatalogDataset.visibility == visibility.upper())
    if classification:
        query = query.where(CatalogDataset.classification == classification.upper())
    if state:
        query = query.join(CatalogDatasetVersion, CatalogDatasetVersion.dataset_id == CatalogDataset.id).where(CatalogDatasetVersion.state == state.upper()).distinct()
    candidates = session.scalars(query).all()
    visible = [
        item for item in candidates
        if require_dataset_access_or_false(session, principal, item, "dataset.view_metadata")
    ]
    if quality or tag:
        filtered: list[CatalogDataset] = []
        for item in visible:
            summary = _dataset_summary(session, item)
            if quality and summary["quality_status"] != quality.upper():
                continue
            if tag and tag.lower() not in {str(value).lower() for value in summary["tags"]}:
                continue
            filtered.append(item)
        visible = filtered
    reverse = sort.startswith("-")
    key = sort.lstrip("-")
    if key not in {"title", "created_at", "updated_at", "data_kind"}:
        key = "updated_at"
    visible.sort(key=lambda item: getattr(item, key) or datetime.min.replace(tzinfo=timezone.utc), reverse=reverse)
    total = len(visible)
    start = (page - 1) * page_size
    items = visible[start:start + page_size]
    return {
        "items": [_dataset_summary(session, item) for item in items],
        "meta": {"page": page, "page_size": page_size, "total": total, "pages": math.ceil(total / page_size) if total else 0, "sort": sort},
    }


def require_dataset_access_or_false(session: Session, principal: Principal, dataset: CatalogDataset, permission: str) -> bool:
    try:
        require_dataset_access(session, principal, dataset, permission)
        return True
    except PlatformError:
        return False


def _can_manage_collection(principal: Principal, collection: Collection) -> bool:
    return (
        collection.owner_user_id == principal.user_id
        or "workspace_admin" in principal.role_keys
    )


def _collection_payload(
    session: Session,
    principal: Principal,
    collection: Collection,
    *,
    detail: bool = False,
) -> dict[str, Any]:
    owner = session.get(User, collection.owner_user_id)
    members: list[dict[str, Any]] = []
    rows = session.scalars(
        select(CollectionMember)
        .where(CollectionMember.collection_id == collection.id)
        .order_by(CollectionMember.ordinal, CollectionMember.id)
    ).all()
    for member in rows:
        version = session.get(CatalogDatasetVersion, member.dataset_version_id)
        dataset = session.get(CatalogDataset, version.dataset_id) if version else None
        if not dataset or not require_dataset_access_or_false(
            session, principal, dataset, "dataset.view_metadata"
        ):
            continue
        members.append(
            {
                "id": str(member.id),
                "role": member.role,
                "ordinal": member.ordinal,
                "dataset": {
                    "id": str(dataset.id),
                    "slug": dataset.slug,
                    "title": dataset.title,
                    "classification": dataset.classification,
                },
                "version": {
                    "id": str(version.id),
                    "version_label": version.version_label,
                    "state": version.state,
                    "profile_key": version.profile_key,
                },
            }
        )
    return {
        "id": str(collection.id),
        "workspace_id": str(collection.workspace_id),
        "slug": collection.slug,
        "title": collection.title,
        "description": collection.description,
        "tags": collection.tags,
        "status": collection.status,
        "owner": {
            "id": str(collection.owner_user_id),
            "display_name": owner.display_name if owner else "Unknown",
        },
        "can_manage": _can_manage_collection(principal, collection),
        "member_count": len(members),
        "members": members if detail else None,
        "row_version": collection.row_version,
        "created_at": collection.created_at.isoformat() if collection.created_at else None,
        "updated_at": collection.updated_at.isoformat() if collection.updated_at else None,
    }


def _require_collection(
    session: Session, principal: Principal, collection_id: UUID
) -> Collection:
    collection = session.get(Collection, collection_id)
    if collection is None or collection.workspace_id != principal.active_workspace_id:
        raise not_found("Collection")
    return collection


@router.get("/collections")
def list_collections(
    search: str | None = None,
    status: str = "ACTIVE",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "data.catalog.enter")
    query = select(Collection).where(
        Collection.workspace_id == principal.active_workspace_id,
        Collection.status == status.upper(),
    )
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(Collection.title.ilike(term), Collection.description.ilike(term))
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(Collection.updated_at.desc(), Collection.title)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_collection_payload(session, principal, item) for item in rows],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


@router.post("/collections", status_code=201)
def create_collection(
    body: CreateCollectionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "collection.create")
    path = f"/workspaces/{principal.active_workspace_id}/api/data/v1/collections"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    slug = _slug(body.slug or body.title)
    if session.scalar(
        select(Collection.id).where(
            Collection.workspace_id == principal.active_workspace_id,
            Collection.slug == slug,
        )
    ):
        raise conflict(
            "COLLECTION_SLUG_CONFLICT",
            "A collection with this workspace slug already exists.",
            slug=slug,
        )
    item = Collection(
        workspace_id=principal.active_workspace_id,
        slug=slug,
        title=body.title.strip(),
        description=body.description.strip(),
        tags=sorted({tag.strip() for tag in body.tags if tag.strip()}),
        status="ACTIVE",
        owner_user_id=principal.user_id,
    )
    session.add(item)
    session.flush()
    response = _collection_payload(session, principal, item, detail=True)
    _remember(session, principal, key, "POST", path, response, status=201)
    record_event(
        session,
        action="catalog.collection.create",
        resource_type="collection",
        resource_id=item.id,
        outcome="success",
        correlation_id=correlation_id(request),
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"slug": item.slug, "tags": item.tags},
    )
    session.commit()
    return response


@router.get("/collections/{collection_id}")
def get_collection(
    collection_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "data.catalog.enter")
    return _collection_payload(
        session,
        principal,
        _require_collection(session, principal, collection_id),
        detail=True,
    )


@router.patch("/collections/{collection_id}")
def update_collection(
    collection_id: UUID,
    body: UpdateCollectionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "collection.manage")
    path = f"/api/data/v1/collections/{collection_id}"
    cached = _cached(session, principal, key, "PATCH", path)
    if cached:
        return cached
    item = _require_collection(session, principal, collection_id)
    if not _can_manage_collection(principal, item):
        raise not_found("Collection")
    if item.status != "ACTIVE":
        raise conflict("COLLECTION_ARCHIVED", "An archived collection cannot be changed.")
    if item.row_version != body.row_version:
        raise conflict("ROW_VERSION_CONFLICT", "The collection changed; reload and retry.")
    before = {"title": item.title, "description": item.description, "tags": item.tags}
    if body.title is not None:
        item.title = body.title.strip()
    if body.description is not None:
        item.description = body.description.strip()
    if body.tags is not None:
        item.tags = sorted({tag.strip() for tag in body.tags if tag.strip()})
    item.row_version += 1
    session.flush()
    response = _collection_payload(session, principal, item, detail=True)
    _remember(session, principal, key, "PATCH", path, response)
    record_event(
        session,
        action="catalog.collection.update",
        resource_type="collection",
        resource_id=item.id,
        outcome="success",
        correlation_id=correlation_id(request),
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        before=before,
        after={"title": item.title, "description": item.description, "tags": item.tags},
    )
    session.commit()
    return response


@router.post("/collections/{collection_id}/members", status_code=201)
def add_collection_member(
    collection_id: UUID,
    body: AddCollectionMemberRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "collection.manage")
    path = f"/api/data/v1/collections/{collection_id}/members"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    item = _require_collection(session, principal, collection_id)
    if not _can_manage_collection(principal, item):
        raise not_found("Collection")
    if item.status != "ACTIVE":
        raise conflict("COLLECTION_ARCHIVED", "An archived collection cannot be changed.")
    version = session.get(CatalogDatasetVersion, body.dataset_version_id)
    dataset = session.get(CatalogDataset, version.dataset_id) if version else None
    require_dataset_access(session, principal, dataset, "dataset.view_metadata")
    existing = session.scalar(
        select(CollectionMember).where(
            CollectionMember.collection_id == item.id,
            CollectionMember.dataset_version_id == version.id,
        )
    )
    if existing:
        response = _collection_payload(session, principal, item, detail=True)
        _remember(session, principal, key, "POST", path, response, status=201)
        session.commit()
        return response
    session.add(
        CollectionMember(
            collection_id=item.id,
            dataset_id=dataset.id,
            dataset_version_id=version.id,
            role=body.role,
            ordinal=body.ordinal,
        )
    )
    item.row_version += 1
    session.flush()
    response = _collection_payload(session, principal, item, detail=True)
    _remember(session, principal, key, "POST", path, response, status=201)
    record_event(
        session,
        action="catalog.collection.member.add",
        resource_type="collection",
        resource_id=item.id,
        outcome="success",
        correlation_id=correlation_id(request),
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"dataset_version_id": str(version.id), "role": body.role},
    )
    session.commit()
    return response


@router.delete("/collections/{collection_id}/members/{member_id}")
def remove_collection_member(
    collection_id: UUID,
    member_id: UUID,
    request: Request,
    row_version: int = Query(ge=1),
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "collection.manage")
    path = f"/api/data/v1/collections/{collection_id}/members/{member_id}"
    cached = _cached(session, principal, key, "DELETE", path)
    if cached:
        return cached
    item = _require_collection(session, principal, collection_id)
    if not _can_manage_collection(principal, item):
        raise not_found("Collection")
    if item.status != "ACTIVE":
        raise conflict("COLLECTION_ARCHIVED", "An archived collection cannot be changed.")
    if item.row_version != row_version:
        raise conflict("ROW_VERSION_CONFLICT", "The collection changed; reload and retry.")
    member = session.get(CollectionMember, member_id)
    if member is None or member.collection_id != item.id:
        raise not_found("Collection member")
    removed_version = member.dataset_version_id
    session.delete(member)
    item.row_version += 1
    session.flush()
    response = _collection_payload(session, principal, item, detail=True)
    _remember(session, principal, key, "DELETE", path, response)
    record_event(
        session,
        action="catalog.collection.member.remove",
        resource_type="collection",
        resource_id=item.id,
        outcome="success",
        correlation_id=correlation_id(request),
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        before={"dataset_version_id": str(removed_version)},
    )
    session.commit()
    return response


@router.post("/collections/{collection_id}/archive")
def archive_collection(
    collection_id: UUID,
    body: ArchiveCollectionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "collection.manage")
    path = f"/api/data/v1/collections/{collection_id}/archive"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    item = _require_collection(session, principal, collection_id)
    if not _can_manage_collection(principal, item):
        raise not_found("Collection")
    if item.row_version != body.row_version:
        raise conflict("ROW_VERSION_CONFLICT", "The collection changed; reload and retry.")
    item.status = "ARCHIVED"
    item.row_version += 1
    session.flush()
    response = _collection_payload(session, principal, item, detail=True)
    _remember(session, principal, key, "POST", path, response)
    record_event(
        session,
        action="catalog.collection.archive",
        resource_type="collection",
        resource_id=item.id,
        outcome="success",
        correlation_id=correlation_id(request),
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        reason=body.reason,
    )
    session.commit()
    return response


@router.post("/datasets", status_code=201)
def create_dataset(
    body: CreateDatasetRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.create")
    path = f"/workspaces/{principal.active_workspace_id}/api/data/v1/datasets"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    slug = _slug(body.slug or body.title)
    if session.scalar(select(CatalogDataset.id).where(CatalogDataset.workspace_id == principal.active_workspace_id, CatalogDataset.slug == slug)):
        raise conflict("DATASET_SLUG_CONFLICT", "A dataset with this workspace slug already exists.", slug=slug)
    dataset = CatalogDataset(
        workspace_id=principal.active_workspace_id,
        slug=slug,
        title=body.title.strip(),
        abstract=body.abstract.strip(),
        data_kind=body.data_kind,
        owner_user_id=principal.user_id,
        visibility=body.visibility,
        classification=body.classification,
        licence_code=body.licence_code,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    session.add(dataset)
    session.flush()
    response = _dataset_summary(session, dataset)
    record_event(
        session, action="catalog.dataset.create", resource_type="dataset", resource_id=dataset.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, after=response,
    )
    _remember(session, principal, key, "POST", path, response, 201)
    session.commit()
    return response


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: UUID, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    dataset = require_dataset_access(session, principal, session.get(CatalogDataset, dataset_id), "dataset.view_metadata")
    payload = _dataset_summary(session, dataset)
    payload["versions"] = [
        _version_payload(session, version)
        for version in session.scalars(
            select(CatalogDatasetVersion).where(CatalogDatasetVersion.dataset_id == dataset.id).order_by(CatalogDatasetVersion.created_at.desc())
        ).all()
    ]
    return payload


@router.patch("/datasets/{dataset_id}")
def update_dataset(
    dataset_id: UUID,
    body: UpdateDatasetRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset = require_dataset_access(session, principal, session.get(CatalogDataset, dataset_id), "dataset.edit_metadata")
    path = f"/api/data/v1/datasets/{dataset_id}"
    cached = _cached(session, principal, key, "PATCH", path)
    if cached:
        return cached
    if dataset.row_version != body.row_version:
        raise conflict("OPTIMISTIC_LOCK_CONFLICT", "The dataset changed since it was loaded.", current_row_version=dataset.row_version)
    next_visibility = body.visibility or dataset.visibility
    next_classification = body.classification or dataset.classification
    if next_classification == "SENSITIVE_FIELD" and next_visibility == "PUBLIC":
        raise conflict("CLASSIFICATION_VISIBILITY_CONFLICT", "SENSITIVE_FIELD data cannot be PUBLIC.")
    before = _dataset_summary(session, dataset)
    for field_name in ("title", "abstract", "visibility", "classification", "licence_code"):
        value = getattr(body, field_name)
        if value is not None:
            setattr(dataset, field_name, value)
    dataset.updated_by = principal.user_id
    dataset.row_version += 1
    session.flush()
    response = _dataset_summary(session, dataset)
    record_event(
        session, action="catalog.dataset.update", resource_type="dataset", resource_id=dataset.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, before=before, after=response,
    )
    _remember(session, principal, key, "PATCH", path, response)
    session.commit()
    return response


@router.get("/datasets/{dataset_id}/versions")
def list_versions(dataset_id: UUID, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    dataset = require_dataset_access(session, principal, session.get(CatalogDataset, dataset_id), "dataset.view_metadata")
    rows = session.scalars(select(CatalogDatasetVersion).where(CatalogDatasetVersion.dataset_id == dataset.id).order_by(CatalogDatasetVersion.created_at.desc())).all()
    return {"items": [_version_payload(session, row) for row in rows], "meta": {"total": len(rows)}}


@router.post("/datasets/{dataset_id}/versions", status_code=201)
def create_version(
    dataset_id: UUID,
    body: CreateVersionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset = require_dataset_access(session, principal, session.get(CatalogDataset, dataset_id), "dataset.upload_version")
    path = f"/api/data/v1/datasets/{dataset_id}/versions"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    if session.scalar(select(CatalogDatasetVersion.id).where(CatalogDatasetVersion.dataset_id == dataset.id, CatalogDatasetVersion.version_label == body.version_label.strip())):
        raise conflict("DATASET_VERSION_LABEL_CONFLICT", "This dataset already has that version label.")
    if body.supersedes_version_id:
        superseded = session.get(CatalogDatasetVersion, body.supersedes_version_id)
        if superseded is None or superseded.dataset_id != dataset.id:
            raise conflict(
                "INVALID_SUPERSEDED_VERSION",
                "A version may only supersede another version of the same dataset.",
            )
    version = CatalogDatasetVersion(
        dataset_id=dataset.id,
        version_label=body.version_label.strip(),
        state="DRAFT",
        profile_key=body.profile_key,
        change_summary=body.change_summary,
        supersedes_version_id=body.supersedes_version_id,
        created_by=principal.user_id,
    )
    session.add(version)
    session.flush()
    metadata = MetadataRecord(dataset_version_id=version.id, **body.metadata.model_dump())
    session.add(metadata)
    session.flush()
    response = _version_payload(session, version)
    record_event(
        session, action="catalog.version.create", resource_type="dataset_version", resource_id=version.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, after={"state": version.state, "profile_key": version.profile_key},
    )
    _remember(session, principal, key, "POST", path, response, 201)
    session.commit()
    return response


@router.get("/versions/{version_id}")
def get_version(version_id: UUID, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    dataset, version = _dataset_for_version(session, version_id)
    require_dataset_access(session, principal, dataset, "dataset.view_metadata")
    return _version_payload(session, version)


@router.patch("/versions/{version_id}")
def update_version(
    version_id: UUID,
    body: UpdateVersionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset, version = _dataset_for_version(session, version_id)
    require_dataset_access(session, principal, dataset, "dataset.edit_metadata")
    path = f"/api/data/v1/versions/{version_id}"
    cached = _cached(session, principal, key, "PATCH", path)
    if cached:
        return cached
    if version.state not in {"DRAFT", "VALIDATION_FAILED", "CHANGES_REQUESTED"}:
        raise conflict("DATASET_VERSION_IMMUTABLE", "This version can no longer be edited.")
    if version.row_version != body.row_version:
        raise conflict("OPTIMISTIC_LOCK_CONFLICT", "The version changed since it was loaded.", current_row_version=version.row_version)
    if body.reviewer_group_id:
        reviewer_group = session.get(Group, body.reviewer_group_id)
        if reviewer_group is None or reviewer_group.workspace_id != principal.active_workspace_id:
            raise not_found("Reviewer group")
    if body.change_summary is not None:
        version.change_summary = body.change_summary
    if body.metadata is not None:
        metadata = session.scalar(select(MetadataRecord).where(MetadataRecord.dataset_version_id == version.id))
        if metadata is None:
            metadata = MetadataRecord(dataset_version_id=version.id, **body.metadata.model_dump())
            session.add(metadata)
        else:
            for field_name, value in body.metadata.model_dump().items():
                setattr(metadata, field_name, value)
    version.row_version += 1
    record_event(
        session, action="catalog.version.update", resource_type="dataset_version", resource_id=version.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, after={"state": version.state, "row_version": version.row_version},
    )
    response = _version_payload(session, version)
    _remember(session, principal, key, "PATCH", path, response)
    session.commit()
    return response


@router.post("/versions/{version_id}/upload-sessions", status_code=201)
def create_upload_session(
    version_id: UUID,
    body: CreateUploadSessionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset, version = _dataset_for_version(session, version_id)
    require_dataset_access(session, principal, dataset, "dataset.upload_version")
    existing = session.scalar(
        select(UploadSession).where(
            UploadSession.created_by == principal.user_id,
            UploadSession.idempotency_key == key,
            UploadSession.dataset_version_id == version.id,
        )
    )
    if existing:
        files = session.scalars(select(UploadSessionFile).where(UploadSessionFile.upload_session_id == existing.id)).all()
        return _upload_session_response(existing, files)
    if version.state not in {"DRAFT", "VALIDATION_FAILED"}:
        raise conflict("INVALID_VERSION_TRANSITION", "Only draft or failed versions can start an upload.", state=version.state)
    total_size = sum(item.size_bytes for item in body.files)
    if total_size > MAX_DATA_HUB_UPLOAD_BYTES:
        raise PlatformError("UPLOAD_TOO_LARGE", "The upload exceeds the configured Data Hub limit.", 413, {"limit_bytes": MAX_DATA_HUB_UPLOAD_BYTES})
    upload = UploadSession(
        workspace_id=principal.active_workspace_id,
        dataset_version_id=version.id,
        created_by=principal.user_id,
        status="OPEN",
        expires_at=now() + timedelta(seconds=PRESIGNED_URL_TTL_SECONDS),
        idempotency_key=key,
    )
    session.add(upload)
    session.flush()
    files: list[UploadSessionFile] = []
    for item in body.files:
        file_row = UploadSessionFile(
            upload_session_id=upload.id,
            filename=item.filename,
            media_type=item.media_type,
            expected_size=item.size_bytes,
            expected_sha256=item.sha256,
            quarantine_object_key=f"quarantine/{principal.active_workspace_id}/{upload.id}/{UUID(int=len(files) + 1)}",
        )
        session.add(file_row)
        session.flush()
        files.append(file_row)
    version.state = "UPLOADING"
    record_event(
        session, action="catalog.upload_session.create", resource_type="upload_session", resource_id=upload.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, after={"dataset_version_id": str(version.id), "file_count": len(files)},
    )
    session.commit()
    return _upload_session_response(upload, files)


def _upload_session_response(upload: UploadSession, files: list[UploadSessionFile]) -> dict[str, Any]:
    return {
        "id": str(upload.id),
        "dataset_version_id": str(upload.dataset_version_id),
        "status": upload.status,
        "expires_at": upload.expires_at.isoformat(),
        "files": [
            {
                "id": str(item.id), "filename": item.filename, "media_type": item.media_type,
                "size_bytes": item.expected_size, "upload_url": presigned_put(item.quarantine_object_key),
                "method": "PUT", "multipart": False,
            }
            for item in files
        ],
    }


@router.post("/upload-sessions/{upload_session_id}/complete")
def complete_upload_session(
    upload_session_id: UUID,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    upload = session.get(UploadSession, upload_session_id)
    if upload is None or upload.workspace_id != principal.active_workspace_id:
        raise not_found("Upload session")
    dataset, version = _dataset_for_version(session, upload.dataset_version_id)
    require_dataset_access(session, principal, dataset, "dataset.upload_version")
    existing_job = session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.resource_id == version.id,
            ProcessingJob.idempotency_key == f"upload-complete:{upload.id}",
        )
    )
    if existing_job:
        return _job_payload(session, existing_job)
    if upload.status != "OPEN" or version.state != "UPLOADING":
        raise conflict("UPLOAD_SESSION_NOT_OPEN", "The upload session is not open.", status=upload.status)
    if upload.expires_at < now():
        upload.status = "EXPIRED"
        session.commit()
        raise conflict("UPLOAD_SESSION_EXPIRED", "The upload session expired; create a new one.")
    files = session.scalars(select(UploadSessionFile).where(UploadSessionFile.upload_session_id == upload.id)).all()
    for item in files:
        try:
            stored = stat_object(item.quarantine_object_key)
        except Exception as error:
            raise conflict("UPLOAD_OBJECT_MISSING", "One or more uploaded objects are missing.", file_id=str(item.id)) from error
        if stored.size != item.expected_size:
            raise conflict("UPLOAD_SIZE_MISMATCH", "The stored object size does not match the upload declaration.", file_id=str(item.id), expected=item.expected_size, actual=stored.size)
        item.uploaded_size = stored.size
        item.etag = stored.etag
    job = ProcessingJob(
        workspace_id=principal.active_workspace_id,
        job_type="catalog:validate-version:v1",
        module_key="data-hub",
        resource_type="dataset_version",
        resource_id=version.id,
        status="QUEUED",
        progress=0,
        idempotency_key=f"upload-complete:{upload.id}",
        payload_json={"upload_session_id": str(upload.id)},
        max_attempts=3,
        requested_by=principal.user_id,
    )
    session.add(job)
    session.flush()
    for ordinal, (step_key, label) in enumerate(
        [("inspect", "Inspect source objects"), ("scan", "Scan files"), ("validate", "Validate profile"), ("register", "Register assets and lineage")],
        start=1,
    ):
        from app.platform_models import JobStep
        session.add(JobStep(job_id=job.id, ordinal=ordinal, step_key=step_key, label=label))
    upload.status = "COMPLETE"
    upload.completed_at = now()
    version.state = "PROCESSING"
    record_event(
        session, action="catalog.upload_session.complete", resource_type="upload_session", resource_id=upload.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, after={"job_id": str(job.id)},
    )
    session.commit()
    process_upload_session.delay(str(upload.id), str(job.id), correlation_id(request))
    return _job_payload(session, job)


def _job_payload(session: Session, job: ProcessingJob) -> dict[str, Any]:
    from app.platform_models import JobStep
    steps = session.scalars(select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.ordinal)).all()
    return {
        "id": str(job.id), "job_type": job.job_type, "resource_type": job.resource_type,
        "resource_id": str(job.resource_id), "status": job.status, "progress": job.progress,
        "attempt": job.attempt, "max_attempts": job.max_attempts,
        "result": job.result_json, "error": ({"code": job.error_code, "message": job.error_message} if job.error_code else None),
        "steps": [
            {"key": step.step_key, "label": step.label, "status": step.status, "details": step.details_json}
            for step in steps
        ],
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/versions/{version_id}/submit-review")
def submit_review(
    version_id: UUID,
    body: SubmitReviewRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset, version = _dataset_for_version(session, version_id)
    require_dataset_access(session, principal, dataset, "dataset.submit_review")
    path = f"/api/data/v1/versions/{version_id}/submit-review"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    if version.state not in {"VALIDATED", "CHANGES_REQUESTED"}:
        raise conflict("INVALID_VERSION_TRANSITION", "Only validated or changes-requested versions can enter review.", state=version.state)
    if version.row_version != body.row_version:
        raise conflict("OPTIMISTIC_LOCK_CONFLICT", "The version changed since it was loaded.", current_row_version=version.row_version)
    review = ReviewRequest(
        dataset_version_id=version.id,
        review_type=body.review_type,
        requested_by=principal.user_id,
        reviewer_group_id=body.reviewer_group_id,
        status="OPEN",
        policy_snapshot={"creator_cannot_be_sole_reviewer": True, "reviewer_does_not_imply_publisher": True},
    )
    session.add(review)
    session.flush()
    version.state = "IN_REVIEW"
    version.submitted_at = now()
    record_event(
        session, action="catalog.review.submit", resource_type="review_request", resource_id=review.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, after={"review_type": review.review_type},
    )
    response = {"id": str(review.id), "dataset_version_id": str(version.id), "review_type": review.review_type, "status": review.status}
    _remember(session, principal, key, "POST", path, response)
    session.commit()
    return response


@router.get("/reviews")
def list_reviews(
    status: str | None = "OPEN",
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.review")
    query = (
        select(ReviewRequest, CatalogDatasetVersion, CatalogDataset)
        .join(CatalogDatasetVersion, CatalogDatasetVersion.id == ReviewRequest.dataset_version_id)
        .join(CatalogDataset, CatalogDataset.id == CatalogDatasetVersion.dataset_id)
        .where(CatalogDataset.workspace_id == principal.active_workspace_id)
        .where(
            or_(
                ReviewRequest.reviewer_group_id.is_(None),
                ReviewRequest.reviewer_group_id.in_(principal.group_ids),
            )
        )
        .order_by(ReviewRequest.requested_at.desc())
    )
    if status:
        query = query.where(ReviewRequest.status == status.upper())
    rows = session.execute(query).all()
    return {
        "items": [
            {
                "id": str(review.id), "review_type": review.review_type, "status": review.status,
                "requested_at": review.requested_at.isoformat(), "requested_by": str(review.requested_by),
                "dataset": {"id": str(dataset.id), "title": dataset.title},
                "version": {"id": str(version.id), "version_label": version.version_label, "state": version.state, "created_by": str(version.created_by)},
            }
            for review, version, dataset in rows
        ],
        "meta": {"total": len(rows)},
    }


@router.post("/reviews/{review_id}/decisions")
def decide_review(
    review_id: UUID,
    body: ReviewDecisionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.review")
    path = f"/api/data/v1/reviews/{review_id}/decisions"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    review = session.get(ReviewRequest, review_id)
    if review is None or review.status not in {"OPEN", "IN_PROGRESS"}:
        raise not_found("Review request")
    dataset, version = _dataset_for_version(session, review.dataset_version_id)
    require_dataset_access(session, principal, dataset, "dataset.view_metadata")
    if version.state != "IN_REVIEW":
        raise conflict("INVALID_VERSION_TRANSITION", "The version is not in review.", state=version.state)
    same_actor = version.created_by == principal.user_id
    if same_actor and not body.exception_reason:
        raise conflict("SEPARATION_OF_DUTIES", "The version creator cannot be its sole reviewer. Use a different persona or record a pilot exception.")
    decision = ReviewDecision(
        review_request_id=review.id,
        reviewer_id=principal.user_id,
        decision=body.decision,
        rationale=body.rationale,
        checklist_snapshot=body.checklist_snapshot,
        exception_reason=body.exception_reason,
    )
    session.add(decision)
    if body.decision == "APPROVE":
        review.status = "APPROVED"
        version.state = "APPROVED"
        version.approved_by = principal.user_id
        version.approved_at = now()
    elif body.decision == "CHANGES_REQUESTED":
        review.status = "CHANGES_REQUESTED"
        version.state = "CHANGES_REQUESTED"
    else:
        review.status = "REJECTED"
        version.state = "CHANGES_REQUESTED"
    record_event(
        session, action="catalog.review.decision", resource_type="review_request", resource_id=review.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, reason=body.rationale,
        after={"decision": body.decision, "version_state": version.state, "exception": bool(body.exception_reason)},
        severity="HIGH" if body.exception_reason else "INFO",
    )
    session.flush()
    response = {"id": str(decision.id), "review_id": str(review.id), "decision": decision.decision, "version_state": version.state}
    _remember(session, principal, key, "POST", path, response)
    session.commit()
    return response


@router.post("/versions/{version_id}/publish")
def publish_version(
    version_id: UUID,
    body: PublishRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.publish")
    dataset, version = _dataset_for_version(session, version_id)
    if dataset.workspace_id != principal.active_workspace_id:
        raise not_found("Dataset version")
    path = f"/api/data/v1/versions/{version_id}/publish"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    if version.state != "APPROVED":
        raise conflict("INVALID_VERSION_TRANSITION", "Only an approved version can be published.", state=version.state)
    if version.row_version != body.row_version:
        raise conflict("OPTIMISTIC_LOCK_CONFLICT", "The version changed since it was loaded.", current_row_version=version.row_version)
    blocking = session.scalar(
        select(func.count(QualityIssue.id))
        .join(QualityRun, QualityRun.id == QualityIssue.quality_run_id)
        .where(
            QualityRun.dataset_version_id == version.id,
            QualityIssue.severity == "BLOCKING",
            QualityIssue.resolution_status == "OPEN",
        )
    ) or 0
    if blocking:
        raise conflict("BLOCKING_QUALITY_ISSUES", "Open blocking quality issues prevent publication.", count=blocking)
    approved_review = session.scalar(
        select(ReviewRequest.id).where(ReviewRequest.dataset_version_id == version.id, ReviewRequest.status == "APPROVED")
    )
    if not approved_review:
        raise conflict("APPROVED_REVIEW_REQUIRED", "An approved review is required before publication.")
    assets = session.scalars(select(CatalogAsset).where(CatalogAsset.dataset_version_id == version.id)).all()
    allowed_scan = {"CLEAN"} | ({"BYPASSED_DEV"} if APP_ENV in {"development", "test"} else set())
    if not assets or any(asset.scan_status not in allowed_scan for asset in assets):
        raise conflict("FILE_SCAN_POLICY_NOT_MET", "Source files do not satisfy the active scan policy.")
    metadata = session.scalar(select(MetadataRecord).where(MetadataRecord.dataset_version_id == version.id))
    if metadata is None or not all([metadata.title, metadata.abstract, metadata.provenance, metadata.use_limitation]):
        raise conflict("METADATA_INCOMPLETE", "Required publication metadata are incomplete.")
    if version.created_by == principal.user_id and not body.exception_reason:
        raise conflict("SEPARATION_OF_DUTIES", "The version creator cannot publish their own version without a recorded pilot exception.")
    version.metadata_snapshot = {
        "title": metadata.title,
        "abstract": metadata.abstract,
        "purpose": metadata.purpose,
        "producer": metadata.producer,
        "provenance": metadata.provenance,
        "licence_code": metadata.licence_code,
        "use_limitation": metadata.use_limitation,
        "crs": metadata.crs,
        "methodology": metadata.methodology,
        "quality_statement": metadata.quality_statement,
        "keywords": metadata.keywords,
        "classification": dataset.classification,
        "visibility": dataset.visibility,
    }
    version.state = "PUBLISHED"
    version.published_by = principal.user_id
    version.published_at = now()
    dataset.current_published_version_id = version.id
    dataset.updated_by = principal.user_id
    dataset.row_version += 1
    session.flush()
    response = _version_payload(session, version)
    record_event(
        session, action="catalog.version.publish", resource_type="dataset_version", resource_id=version.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, reason=body.exception_reason,
        after={"state": version.state, "metadata_snapshot_frozen": True},
        severity="HIGH" if body.exception_reason else "INFO",
    )
    _remember(session, principal, key, "POST", path, response)
    session.commit()
    return response


@router.post("/versions/{version_id}/deprecate")
def deprecate_version(
    version_id: UUID,
    body: DeprecateRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.deprecate")
    dataset, version = _dataset_for_version(session, version_id)
    if dataset.workspace_id != principal.active_workspace_id:
        raise not_found("Dataset version")
    path = f"/api/data/v1/versions/{version_id}/deprecate"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    if version.state != "PUBLISHED":
        raise conflict("INVALID_VERSION_TRANSITION", "Only a published version can be deprecated.", state=version.state)
    if version.row_version != body.row_version:
        raise conflict("OPTIMISTIC_LOCK_CONFLICT", "The version changed since it was loaded.", current_row_version=version.row_version)
    version.state = "DEPRECATED"
    version.deprecated_at = now()
    if dataset.current_published_version_id == version.id:
        dataset.current_published_version_id = None
    record_event(
        session, action="catalog.version.deprecate", resource_type="dataset_version", resource_id=version.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, reason=body.reason, after={"state": version.state},
    )
    response = _version_payload(session, version)
    _remember(session, principal, key, "POST", path, response)
    session.commit()
    return response


@router.post("/datasets/{dataset_id}/archive")
def archive_dataset(
    dataset_id: UUID,
    body: DeprecateRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.archive")
    dataset = session.get(CatalogDataset, dataset_id)
    if dataset is None or dataset.workspace_id != principal.active_workspace_id:
        raise not_found("Dataset")
    path = f"/api/data/v1/datasets/{dataset_id}/archive"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    if dataset.row_version != body.row_version:
        raise conflict("OPTIMISTIC_LOCK_CONFLICT", "The dataset changed since it was loaded.", current_row_version=dataset.row_version)
    versions = session.scalars(
        select(CatalogDatasetVersion).where(CatalogDatasetVersion.dataset_id == dataset.id)
    ).all()
    published_versions = [version for version in versions if version.state == "PUBLISHED"]
    if published_versions:
        raise conflict(
            "DATASET_HAS_PUBLISHED_VERSIONS",
            "Deprecate every published version before archiving the dataset.",
            count=len(published_versions),
        )
    version_ids = [version.id for version in versions]
    active_jobs = 0
    if version_ids:
        active_jobs = session.scalar(
            select(func.count(ProcessingJob.id)).where(
                ProcessingJob.resource_id.in_(version_ids),
                ProcessingJob.status.in_(["QUEUED", "RUNNING"]),
            )
        ) or 0
    if active_jobs:
        raise conflict(
            "DATASET_HAS_ACTIVE_JOBS",
            "Wait for active processing jobs to finish before archiving this dataset.",
            count=active_jobs,
        )
    cancelled_reviews = []
    if version_ids:
        cancelled_reviews = session.scalars(
            select(ReviewRequest).where(
                ReviewRequest.dataset_version_id.in_(version_ids),
                ReviewRequest.status.in_(["OPEN", "IN_PROGRESS"]),
            )
        ).all()
    for review in cancelled_reviews:
        review.status = "CANCELLED"
    cancelled_uploads = []
    if version_ids:
        cancelled_uploads = session.scalars(
            select(UploadSession).where(
                UploadSession.dataset_version_id.in_(version_ids),
                UploadSession.status == "OPEN",
            )
        ).all()
    for upload in cancelled_uploads:
        upload.status = "CANCELLED"
        upload.completed_at = now()
    archived_versions = 0
    for version in versions:
        if version.state != "ARCHIVED":
            version.state = "ARCHIVED"
            version.archived_at = now()
            archived_versions += 1
    dataset.lifecycle_status = "ARCHIVED"
    dataset.current_published_version_id = None
    dataset.row_version += 1
    record_event(
        session, action="catalog.dataset.archive", resource_type="dataset", resource_id=dataset.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, reason=body.reason,
        after={
            "lifecycle_status": "ARCHIVED",
            "archived_versions": archived_versions,
            "cancelled_reviews": len(cancelled_reviews),
            "cancelled_upload_sessions": len(cancelled_uploads),
        },
    )
    response = _dataset_summary(session, dataset)
    _remember(session, principal, key, "POST", path, response)
    session.commit()
    return response


@router.get("/datasets/{dataset_id}/grants")
def list_grants(dataset_id: UUID, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    dataset = require_dataset_access(session, principal, session.get(CatalogDataset, dataset_id), "dataset.manage_access")
    grants = session.scalars(select(PermissionGrant).where(PermissionGrant.resource_type == "dataset", PermissionGrant.resource_id == dataset.id).order_by(PermissionGrant.created_at.desc())).all()
    return {"items": [_grant_payload(item) for item in grants], "meta": {"total": len(grants)}}


def _grant_payload(grant: PermissionGrant) -> dict[str, Any]:
    return {
        "id": str(grant.id), "subject_type": grant.subject_type, "subject_id": str(grant.subject_id),
        "permission_code": grant.permission_code, "effect": grant.effect,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "reason": grant.reason, "created_by": str(grant.created_by),
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
    }


@router.post("/datasets/{dataset_id}/grants", status_code=201)
def create_grant(
    dataset_id: UUID,
    body: CreateGrantRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset = require_dataset_access(session, principal, session.get(CatalogDataset, dataset_id), "dataset.manage_access")
    path = f"/api/data/v1/datasets/{dataset_id}/grants"
    cached = _cached(session, principal, key, "POST", path)
    if cached:
        return cached
    if body.subject_type == "user":
        subject = session.get(User, body.subject_id)
        membership = session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == principal.active_workspace_id,
                WorkspaceMembership.user_id == body.subject_id,
                WorkspaceMembership.status == "active",
                or_(
                    WorkspaceMembership.expires_at.is_(None),
                    WorkspaceMembership.expires_at > now(),
                ),
            )
        )
        if subject is None or subject.status != "active" or membership is None:
            raise not_found("Grant subject")
    else:
        subject = session.get(Group, body.subject_id)
        if subject is None or subject.workspace_id != principal.active_workspace_id:
            raise not_found("Grant subject")
    grant = PermissionGrant(
        workspace_id=principal.active_workspace_id,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        resource_type="dataset",
        resource_id=dataset.id,
        permission_code=body.permission_code,
        effect=body.effect,
        expires_at=body.expires_at,
        created_by=principal.user_id,
        reason=body.reason,
    )
    session.add(grant)
    session.flush()
    record_event(
        session, action="governance.grant.create", resource_type="permission_grant", resource_id=grant.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, reason=body.reason, after=_grant_payload(grant),
        severity="HIGH" if body.effect == "DENY" else "INFO",
    )
    response = _grant_payload(grant)
    _remember(session, principal, key, "POST", path, response, 201)
    session.commit()
    return response


@router.delete("/datasets/{dataset_id}/grants/{grant_id}")
def delete_grant(
    dataset_id: UUID,
    grant_id: UUID,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset = require_dataset_access(session, principal, session.get(CatalogDataset, dataset_id), "dataset.manage_access")
    path = f"/api/data/v1/datasets/{dataset_id}/grants/{grant_id}"
    cached = _cached(session, principal, key, "DELETE", path)
    if cached:
        return cached
    grant = session.get(PermissionGrant, grant_id)
    if (
        grant is None
        or grant.workspace_id != principal.active_workspace_id
        or grant.resource_type != "dataset"
        or grant.resource_id != dataset.id
    ):
        raise not_found("Grant")
    before = _grant_payload(grant)
    session.delete(grant)
    record_event(
        session, action="governance.grant.delete", resource_type="permission_grant", resource_id=grant.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, before=before,
    )
    response = {"deleted": True, "id": str(grant_id)}
    _remember(session, principal, key, "DELETE", path, response)
    session.commit()
    return response


@router.get("/versions/{version_id}/download")
def download_version(
    version_id: UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset, version = _dataset_for_version(session, version_id)
    require_dataset_access(session, principal, dataset, "dataset.download")
    asset = session.scalar(select(CatalogAsset).where(CatalogAsset.dataset_version_id == version.id, CatalogAsset.role == "source").order_by(CatalogAsset.created_at).limit(1))
    if asset is None:
        raise not_found("Download asset")
    expires_at = now() + timedelta(seconds=PRESIGNED_URL_TTL_SECONDS)
    record_event(
        session, action="catalog.asset.download", resource_type="dataset_version", resource_id=version.id,
        outcome="success", correlation_id=correlation_id(request), actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id, after={"expires_at": expires_at.isoformat(), "asset_id": str(asset.id)},
    )
    session.commit()
    return {"url": presigned_get(asset.object_key), "expires_at": expires_at.isoformat(), "filename": asset.filename, "media_type": asset.media_type}


def _vector_page(
    payload: bytes,
    *,
    page: int,
    page_size: int,
    simplify_tolerance: float,
) -> tuple[dict[str, Any], int]:
    document = json.loads(payload.decode("utf-8-sig"))
    features = document.get("features", []) if isinstance(document, dict) else []
    if not isinstance(features, list):
        raise ValueError("GeoJSON features must be an array")
    preview_cap = min(len(features), 2000)
    start = (page - 1) * page_size
    selected = features[start : min(start + page_size, preview_cap)]
    simplified: list[dict[str, Any]] = []
    for feature in selected:
        next_feature = dict(feature)
        raw_geometry = feature.get("geometry")
        if raw_geometry and simplify_tolerance > 0:
            geometry = shape(raw_geometry)
            if geometry.geom_type in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
                next_feature["geometry"] = mapping(
                    geometry.simplify(simplify_tolerance, preserve_topology=True)
                )
        simplified.append(next_feature)
    return {"type": "FeatureCollection", "features": simplified}, len(features)


def _table_page(
    payload: bytes,
    *,
    page: int,
    page_size: int,
    redact_sensitive: bool,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    redacted_fields: list[str] = []
    if redact_sensitive and rows:
        protected = {"area_code", "admin_code", "case_code"}
        redacted_fields = [
            field
            for field in rows[0]
            if field not in protected
            and re.search(r"(^|_)(name|phone|email|person|farmer|contact|identifier|id)($|_)", field, re.I)
        ]
    start = (page - 1) * page_size
    selected = rows[start : start + page_size]
    for row in selected:
        for field in redacted_fields:
            if row.get(field):
                row[field] = "[REDACTED]"
    sample = rows[:10000]
    missing = {
        field: sum(not str(row.get(field, "")).strip() for row in sample)
        for field in (rows[0].keys() if rows else [])
    }
    return selected, len(rows), {
        "missing_values": missing,
        "sampled_rows": len(sample),
        "approximate": len(rows) > len(sample),
        "redacted_fields": redacted_fields,
    }


@router.get("/versions/{version_id}/preview")
def preview_version(
    version_id: UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    simplify_tolerance: float = Query(default=0.002, ge=0, le=1),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    dataset, version = _dataset_for_version(session, version_id)
    require_dataset_access(session, principal, dataset, "dataset.preview")
    representation = session.scalar(
        select(Representation)
        .where(
            Representation.dataset_version_id == version.id,
            Representation.status == "READY",
        )
        .order_by(Representation.created_at.desc())
        .limit(1)
    )
    asset = session.scalar(
        select(CatalogAsset)
        .where(CatalogAsset.dataset_version_id == version.id, CatalogAsset.role == "source")
        .order_by(CatalogAsset.created_at)
        .limit(1)
    )
    if representation is None:
        raise not_found("Preview")
    preview = representation.preview_json
    total = int(representation.schema_json.get("record_count", 0) or 0)
    statistics = dict(representation.statistics_json or {})
    preview_kind = "metadata"
    simplified = False
    if asset:
        try:
            payload = get_bytes(asset.object_key)
            if dataset.data_kind == "vector" or asset.filename.lower().endswith(
                (".geojson", ".json")
            ):
                preview, total = _vector_page(
                    payload,
                    page=page,
                    page_size=page_size,
                    simplify_tolerance=simplify_tolerance,
                )
                preview_kind = "vector"
                simplified = simplify_tolerance > 0
            elif dataset.data_kind == "table" or asset.filename.lower().endswith(".csv"):
                preview, total, table_statistics = _table_page(
                    payload,
                    page=page,
                    page_size=page_size,
                    redact_sensitive=dataset.classification == "SENSITIVE_FIELD",
                )
                statistics = {**statistics, **table_statistics}
                preview_kind = "table"
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            preview_kind = "stored_sample"
    visible_total = min(total, 2000) if preview_kind == "vector" else total
    record_event(
        session,
        action="catalog.version.preview",
        resource_type="dataset_version",
        resource_id=version.id,
        outcome="success",
        correlation_id=correlation_id(request),
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"page": page, "page_size": page_size, "preview_kind": preview_kind},
    )
    session.commit()
    return {
        "representation_type": representation.representation_type,
        "preview_kind": preview_kind,
        "preview": preview,
        "schema": representation.schema_json,
        "statistics": statistics,
        "bbox": representation.bbox_json,
        "crs": representation.crs,
        "geometry_type": representation.geometry_type,
        "page": {"number": page, "size": page_size, "total": visible_total},
        "simplified": simplified,
        "source_asset_unchanged": True,
        "display_cap": 2000 if preview_kind == "vector" else None,
    }


@router.get("/versions/{version_id}/lineage")
def get_lineage(version_id: UUID, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    dataset, version = _dataset_for_version(session, version_id)
    require_dataset_access(session, principal, dataset, "lineage.view")
    rows = session.execute(
        select(LineageEdge, LineageProcess)
        .join(LineageProcess, LineageProcess.id == LineageEdge.process_id)
        .where(LineageEdge.dataset_version_id == version.id)
        .order_by(LineageProcess.started_at.desc())
    ).all()
    return {
        "dataset_version_id": str(version.id),
        "processes": [
            {
                "id": str(process.id), "process_type": process.process_type, "module_key": process.module_key,
                "status": process.status, "method_identifier": process.method_identifier,
                "method_version": process.method_version, "parameters": process.parameters_json,
                "direction": edge.direction, "role": edge.role,
                "started_at": process.started_at.isoformat() if process.started_at else None,
                "completed_at": process.completed_at.isoformat() if process.completed_at else None,
            }
            for edge, process in rows
        ],
    }
