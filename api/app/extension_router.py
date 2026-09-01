from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Header, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit_service import record_event
from app.authorization import assert_permission
from app.config import ALLOW_INSECURE_DEV_FILE_SCAN, APP_ENV
from app.database import get_session
from app.errors import PlatformError, conflict, not_found
from app.extension_models import (
    ActivityPlan,
    ActivityStep,
    AssessmentCandidate,
    CaseAssignment,
    CaseStatusHistory,
    ExtensionCase,
    FollowUp,
    KnowledgeItem,
    KnowledgeSource,
    KnowledgeVersion,
    MediaAsset,
    Observation,
    VerificationItem,
    VerificationResponse,
    VerificationSession,
    VerificationTemplateVersion,
)
from app.identity import Principal, get_current_principal
from app.investment.canonical import checksum_json
from app.object_store import presigned_get, put_bytes
from app.platform_models import IdempotencyRecord, User


router = APIRouter(
    prefix="/api/apps/extension-field-support/v1",
    tags=["Extension Field Support"],
)

CASE_STATES = {
    "NEW": {"ASSIGNED", "CANCELLED"},
    "ASSIGNED": {"IN_OBSERVATION", "CANCELLED"},
    "IN_OBSERVATION": {"IN_VERIFICATION", "CANCELLED"},
    "IN_VERIFICATION": {"ACTION_PLANNED", "CANCELLED"},
    "ACTION_PLANNED": {"FOLLOW_UP", "CANCELLED"},
    "FOLLOW_UP": {"CLOSED", "CANCELLED"},
    "CLOSED": set(),
    "CANCELLED": set(),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _enter(principal: Principal) -> None:
    assert_permission(principal, "apps.extension.use", "extension-field-support")


def require_idempotency_key(
    value: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if not value or len(value) < 8:
        raise PlatformError(
            "EXTENSION_IDEMPOTENCY_KEY_REQUIRED",
            "Extension mutations require an Idempotency-Key of at least 8 characters.",
            400,
        )
    return value[:255]


def _cached(
    session: Session,
    principal: Principal,
    key: str,
    request: Request,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    request_hash = checksum_json(payload)
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == principal.user_id,
            IdempotencyRecord.idempotency_key == key,
            IdempotencyRecord.method == request.method,
            IdempotencyRecord.path == request.url.path,
        )
    )
    if row is None:
        return None, request_hash
    if row.response_json.get("request_hash") != request_hash:
        raise conflict(
            "EXTENSION_IDEMPOTENCY_KEY_CONFLICT",
            "The idempotency key was already used with a different payload.",
        )
    return row.response_json.get("response", {}), request_hash


def _remember(
    session: Session,
    principal: Principal,
    key: str,
    request: Request,
    request_hash: str,
    response: dict[str, Any],
    status: int = 200,
) -> None:
    session.add(
        IdempotencyRecord(
            actor_id=principal.user_id,
            idempotency_key=key,
            method=request.method,
            path=request.url.path,
            response_status=status,
            response_json={"request_hash": request_hash, "response": response},
        )
    )


def _can_view_case(principal: Principal, item: ExtensionCase | None) -> bool:
    if item is None or item.workspace_id != principal.active_workspace_id:
        return False
    if "extension.case.view_workspace" in principal.effective_permissions:
        return True
    return (
        "extension.case.view_assigned" in principal.effective_permissions
        and (item.created_by == principal.user_id or item.current_assignee_id == principal.user_id)
    )


def _require_case(
    session: Session,
    principal: Principal,
    case_id: uuid.UUID,
    *,
    update: bool = False,
) -> ExtensionCase:
    item = session.get(ExtensionCase, case_id)
    if not _can_view_case(principal, item):
        raise not_found("Extension case")
    if update:
        if "extension.case.view_workspace" not in principal.effective_permissions:
            assert_permission(principal, "extension.case.update_assigned", "extension-field-support")
            if item.current_assignee_id != principal.user_id and item.created_by != principal.user_id:
                raise not_found("Extension case")
    return item


def _case_payload(session: Session, item: ExtensionCase, detail: bool = False) -> dict[str, Any]:
    assignee = session.get(User, item.current_assignee_id) if item.current_assignee_id else None
    overdue = session.scalar(
        select(func.count(FollowUp.id)).where(
            FollowUp.case_id == item.id,
            FollowUp.status == "OPEN",
            FollowUp.due_date < date.today(),
        )
    ) or 0
    payload: dict[str, Any] = {
        "id": str(item.id),
        "workspace_id": str(item.workspace_id),
        "case_number": item.case_number,
        "title": item.title,
        "crop": item.crop,
        "growth_stage": item.growth_stage,
        "severity": item.severity,
        "affected_area_ha": item.affected_area_ha,
        "location_label": item.location_label,
        "approximate_location": (
            {"lat": item.approximate_lat, "lon": item.approximate_lon}
            if item.approximate_lat is not None and item.approximate_lon is not None
            else None
        ),
        "priority": item.priority,
        "status": item.status,
        "notes": item.notes,
        "demonstration": item.demonstration,
        "assignee": (
            {"id": str(assignee.id), "display_name": assignee.display_name}
            if assignee
            else None
        ),
        "last_observation_at": item.last_observation_at.isoformat() if item.last_observation_at else None,
        "next_action": item.next_action,
        "overdue_follow_ups": overdue,
        "sync_status": item.sync_status,
        "row_version": item.row_version,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
    if not detail:
        return payload
    observations = session.scalars(
        select(Observation)
        .where(Observation.case_id == item.id)
        .order_by(Observation.observed_at.desc())
    ).all()
    assessments = session.scalars(
        select(AssessmentCandidate)
        .where(AssessmentCandidate.case_id == item.id)
        .order_by(AssessmentCandidate.created_at.desc())
    ).all()
    verifications = session.scalars(
        select(VerificationSession)
        .where(VerificationSession.case_id == item.id)
        .order_by(VerificationSession.revision_number.desc())
    ).all()
    activities = session.scalars(
        select(ActivityPlan)
        .where(ActivityPlan.case_id == item.id)
        .order_by(ActivityPlan.created_at.desc())
    ).all()
    follow_ups = session.scalars(
        select(FollowUp)
        .where(FollowUp.case_id == item.id)
        .order_by(FollowUp.due_date)
    ).all()
    history = session.scalars(
        select(CaseStatusHistory)
        .where(CaseStatusHistory.case_id == item.id)
        .order_by(CaseStatusHistory.changed_at)
    ).all()
    payload.update(
        {
            "assessment": item.assessment_json,
            "observations": [_observation_payload(value) for value in observations],
            "assessments": [_assessment_payload(session, value) for value in assessments],
            "verifications": [_verification_payload(session, value) for value in verifications],
            "activities": [_activity_payload(session, value) for value in activities],
            "follow_ups": [_follow_up_payload(value) for value in follow_ups],
            "history": [
                {
                    "id": str(value.id),
                    "from_status": value.from_status,
                    "to_status": value.to_status,
                    "reason": value.reason,
                    "changed_by": str(value.changed_by),
                    "changed_at": value.changed_at.isoformat(),
                }
                for value in history
            ],
        }
    )
    return payload


def _record_transition(
    session: Session,
    principal: Principal,
    item: ExtensionCase,
    target: str,
    reason: str,
    correlation_id: str,
) -> None:
    if target == item.status:
        return
    if target not in CASE_STATES.get(item.status, set()):
        raise conflict(
            "EXTENSION_CASE_TRANSITION_INVALID",
            f"A case cannot move from {item.status} to {target}.",
            current_status=item.status,
            requested_status=target,
        )
    previous = item.status
    item.status = target
    item.row_version += 1
    item.updated_at = now()
    if target == "CLOSED":
        item.closed_at = now()
        item.next_action = "No further action"
    elif target == "CANCELLED":
        item.cancellation_reason = reason
        item.next_action = "Cancelled with recorded reason"
    session.add(
        CaseStatusHistory(
            workspace_id=item.workspace_id,
            case_id=item.id,
            from_status=previous,
            to_status=target,
            reason=reason,
            changed_by=principal.user_id,
        )
    )
    record_event(
        session,
        action="extension.case.transition",
        resource_type="extension_case",
        resource_id=item.id,
        outcome="success",
        correlation_id=correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        reason=reason,
        before={"status": previous},
        after={"status": target},
    )


def _observation_payload(item: Observation) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "case_id": str(item.case_id),
        "client_uuid": str(item.client_uuid),
        "status": item.status,
        "observed_at": item.observed_at.isoformat(),
        "severity": item.severity,
        "affected_area_ha": item.affected_area_ha,
        "approximate_location": item.approximate_location,
        "notes": item.notes,
        "structured": item.structured_json,
        "created_by": str(item.created_by),
        "row_version": item.row_version,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _knowledge_payload(session: Session, item: KnowledgeItem) -> dict[str, Any]:
    versions = session.scalars(
        select(KnowledgeVersion)
        .where(KnowledgeVersion.knowledge_item_id == item.id)
        .order_by(KnowledgeVersion.version_number.desc())
    ).all()
    return {
        "id": str(item.id),
        "item_key": item.item_key,
        "title": item.title,
        "category": item.category,
        "status": item.status,
        "demonstration": item.demonstration,
        "current_version_id": str(item.current_version_id) if item.current_version_id else None,
        "versions": [
            {
                "id": str(value.id),
                "version_number": value.version_number,
                "status": value.status,
                "content": value.content_json,
                "source_summary": value.source_summary,
                "created_by": str(value.created_by),
                "approved_by": str(value.approved_by) if value.approved_by else None,
                "row_version": value.row_version,
            }
            for value in versions
        ],
    }


def _assessment_payload(session: Session, item: AssessmentCandidate) -> dict[str, Any]:
    knowledge = session.get(KnowledgeVersion, item.knowledge_version_id)
    definition = session.get(KnowledgeItem, knowledge.knowledge_item_id) if knowledge else None
    return {
        "id": str(item.id),
        "case_id": str(item.case_id),
        "status": item.status,
        "possible_cause_category": definition.title if definition else "Unavailable category",
        "knowledge_version_id": str(item.knowledge_version_id),
        "supporting_observation_ids": item.supporting_observation_ids,
        "missing_information": item.missing_information,
        "selected_by": str(item.selected_by),
        "reviewed_by": str(item.reviewed_by) if item.reviewed_by else None,
        "review_reason": item.review_reason,
        "row_version": item.row_version,
    }


def _verification_payload(session: Session, item: VerificationSession) -> dict[str, Any]:
    template = session.get(VerificationTemplateVersion, item.template_version_id)
    template_items = session.scalars(
        select(VerificationItem)
        .where(VerificationItem.template_version_id == item.template_version_id)
        .order_by(VerificationItem.ordinal)
    ).all()
    responses = {
        value.verification_item_id: value
        for value in session.scalars(
            select(VerificationResponse).where(
                VerificationResponse.verification_session_id == item.id
            )
        ).all()
    }
    return {
        "id": str(item.id),
        "case_id": str(item.case_id),
        "revision_number": item.revision_number,
        "status": item.status,
        "template": {
            "id": str(item.template_version_id),
            "name": template.name if template else "Unavailable template",
            "version_number": template.version_number if template else None,
        },
        "items": [
            {
                "id": str(value.id),
                "ordinal": value.ordinal,
                "prompt": value.prompt,
                "response_type": value.response_type,
                "required": value.required,
                "required_evidence": value.required_evidence,
                "response": (
                    responses[value.id].response_json if value.id in responses else None
                ),
                "evidence_note": (
                    responses[value.id].evidence_note if value.id in responses else ""
                ),
            }
            for value in template_items
        ],
        "row_version": item.row_version,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


def _activity_payload(session: Session, item: ActivityPlan) -> dict[str, Any]:
    steps = session.scalars(
        select(ActivityStep)
        .where(ActivityStep.activity_plan_id == item.id)
        .order_by(ActivityStep.ordinal)
    ).all()
    return {
        "id": str(item.id),
        "case_id": str(item.case_id) if item.case_id else None,
        "activity_type": item.activity_type,
        "objective": item.objective,
        "participant_count": item.participant_count,
        "responsible_officer_id": str(item.responsible_officer_id),
        "due_date": item.due_date.isoformat(),
        "status": item.status,
        "outcome": item.outcome,
        "closure_evidence": item.closure_evidence,
        "created_by": str(item.created_by),
        "approved_by": str(item.approved_by) if item.approved_by else None,
        "row_version": item.row_version,
        "steps": [
            {
                "id": str(value.id),
                "ordinal": value.ordinal,
                "description": value.description,
                "status": value.status,
                "due_date": value.due_date.isoformat() if value.due_date else None,
            }
            for value in steps
        ],
    }


def _follow_up_payload(item: FollowUp) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "case_id": str(item.case_id),
        "activity_plan_id": str(item.activity_plan_id) if item.activity_plan_id else None,
        "due_date": item.due_date.isoformat(),
        "status": item.status,
        "objective": item.objective,
        "outcome": item.outcome,
        "overdue": item.status == "OPEN" and item.due_date < date.today(),
        "row_version": item.row_version,
    }


class CaseCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    crop: str = Field(default="Rice", min_length=2, max_length=120)
    growth_stage: str = Field(default="Not recorded", max_length=120)
    severity: Literal["LOW", "MODERATE", "HIGH"] = "MODERATE"
    affected_area_ha: float | None = Field(default=None, ge=0, le=100000)
    location_label: str = Field(default="Approximate location", max_length=240)
    approximate_lat: float | None = Field(default=None, ge=-90, le=90)
    approximate_lon: float | None = Field(default=None, ge=-180, le=180)
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"
    notes: str = Field(default="", max_length=5000)


class AssignRequest(BaseModel):
    officer_id: uuid.UUID
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] | None = None
    reason: str = Field(min_length=3, max_length=2000)
    row_version: int = Field(ge=1)


class TransitionRequest(BaseModel):
    target_status: Literal[
        "ASSIGNED",
        "IN_OBSERVATION",
        "IN_VERIFICATION",
        "ACTION_PLANNED",
        "FOLLOW_UP",
        "CLOSED",
        "CANCELLED",
    ]
    reason: str = Field(min_length=3, max_length=2000)
    row_version: int = Field(ge=1)


class ObservationRequest(BaseModel):
    client_uuid: uuid.UUID
    status: Literal["DRAFT", "COMPLETED"] = "DRAFT"
    observed_at: datetime
    severity: Literal["LOW", "MODERATE", "HIGH"] = "MODERATE"
    affected_area_ha: float | None = Field(default=None, ge=0, le=100000)
    approximate_location: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=10000)
    structured: dict[str, Any] = Field(default_factory=dict)


class ObservationPatchRequest(BaseModel):
    status: Literal["DRAFT", "COMPLETED"]
    notes: str = Field(default="", max_length=10000)
    structured: dict[str, Any] = Field(default_factory=dict)
    row_version: int = Field(ge=1)


class AssessmentRequest(BaseModel):
    knowledge_version_id: uuid.UUID
    supporting_observation_ids: list[uuid.UUID] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=3000)


class AssessmentReviewRequest(BaseModel):
    decision: Literal["CONFIRMED", "REJECTED"]
    reason: str = Field(min_length=3, max_length=2000)
    row_version: int = Field(ge=1)


class VerificationStartRequest(BaseModel):
    template_version_id: uuid.UUID


class VerificationResponseItem(BaseModel):
    verification_item_id: uuid.UUID
    value: Literal["YES", "NO", "UNKNOWN"]
    evidence_note: str = Field(default="", max_length=3000)


class VerificationSaveRequest(BaseModel):
    responses: list[VerificationResponseItem]
    complete: bool = False
    row_version: int = Field(ge=1)


class ActivityCreateRequest(BaseModel):
    case_id: uuid.UUID | None = None
    activity_type: Literal["field_visit", "demo", "group_session", "individual_follow_up"]
    objective: str = Field(min_length=3, max_length=5000)
    participant_count: int = Field(default=0, ge=0, le=100000)
    responsible_officer_id: uuid.UUID
    due_date: date
    steps: list[str] = Field(min_length=1, max_length=20)
    submit_for_approval: bool = True


class ActivityApprovalRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=3, max_length=2000)
    row_version: int = Field(ge=1)


class FollowUpCreateRequest(BaseModel):
    activity_plan_id: uuid.UUID | None = None
    due_date: date
    objective: str = Field(min_length=3, max_length=5000)


class FollowUpCompleteRequest(BaseModel):
    outcome: str = Field(min_length=3, max_length=5000)
    row_version: int = Field(ge=1)


class KnowledgeVersionCreateRequest(BaseModel):
    content: dict[str, Any]
    source_summary: str = Field(min_length=10, max_length=5000)


class KnowledgeApproveRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    row_version: int = Field(ge=1)


class SyncItem(BaseModel):
    client_uuid: uuid.UUID
    mutation_type: Literal["observation.create"]
    case_id: uuid.UUID
    payload: ObservationRequest


class SyncRequest(BaseModel):
    items: list[SyncItem] = Field(max_length=100)


@router.get("/overview")
def overview(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    query = select(ExtensionCase).where(
        ExtensionCase.workspace_id == principal.active_workspace_id
    )
    cases = [value for value in session.scalars(query).all() if _can_view_case(principal, value)]
    return {
        "module": "extension-field-support",
        "non_ai": True,
        "demonstration": True,
        "counts": {
            "visible_cases": len(cases),
            "assigned_cases": sum(value.current_assignee_id == principal.user_id for value in cases),
            "overdue_follow_ups": session.scalar(
                select(func.count(FollowUp.id)).where(
                    FollowUp.workspace_id == principal.active_workspace_id,
                    FollowUp.status == "OPEN",
                    FollowUp.due_date < date.today(),
                    FollowUp.case_id.in_([value.id for value in cases] or [uuid.uuid4()]),
                )
            )
            or 0,
        },
        "scanner_mode": (
            "development_bypass"
            if APP_ENV in {"development", "test"} and ALLOW_INSECURE_DEV_FILE_SCAN
            else "fail_closed_or_operational"
        ),
        "disclaimer": (
            "Demonstration records only. Officers select categories manually; no model, "
            "automated diagnosis or agronomic recommendation is used."
        ),
    }


@router.get("/cases")
def list_cases(
    status: str | None = None,
    priority: str | None = None,
    assigned_to_me: bool = False,
    search: str | None = None,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    query = select(ExtensionCase).where(
        ExtensionCase.workspace_id == principal.active_workspace_id
    )
    if status:
        query = query.where(ExtensionCase.status == status.upper())
    if priority:
        query = query.where(ExtensionCase.priority == priority.upper())
    if assigned_to_me:
        query = query.where(ExtensionCase.current_assignee_id == principal.user_id)
    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                ExtensionCase.title.ilike(term),
                ExtensionCase.case_number.ilike(term),
                ExtensionCase.location_label.ilike(term),
            )
        )
    rows = session.scalars(
        query.order_by(ExtensionCase.priority.desc(), ExtensionCase.updated_at.desc())
    ).all()
    visible = [value for value in rows if _can_view_case(principal, value)]
    return {"items": [_case_payload(session, value) for value in visible], "meta": {"total": len(visible)}}


@router.get("/worklist")
def worklist(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return list_cases(assigned_to_me=True, principal=principal, session=session)


@router.get("/map")
def case_map(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    response = list_cases(principal=principal, session=session)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": item["id"],
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        item["approximate_location"]["lon"],
                        item["approximate_location"]["lat"],
                    ],
                },
                "properties": {
                    "case_number": item["case_number"],
                    "title": item["title"],
                    "status": item["status"],
                    "priority": item["priority"],
                    "demonstration": item["demonstration"],
                },
            }
            for item in response["items"]
            if item["approximate_location"]
        ],
        "approximate_only": True,
    }


@router.post("/cases", status_code=201)
def create_case(
    body: CaseCreateRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.case.create", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    sequence = session.scalar(
        select(func.count(ExtensionCase.id)).where(
            ExtensionCase.workspace_id == principal.active_workspace_id
        )
    ) or 0
    item = ExtensionCase(
        workspace_id=principal.active_workspace_id,
        case_number=f"USR-{sequence + 1:05d}",
        title=body.title,
        crop=body.crop,
        growth_stage=body.growth_stage,
        severity=body.severity,
        affected_area_ha=body.affected_area_ha,
        location_label=body.location_label,
        approximate_lat=body.approximate_lat,
        approximate_lon=body.approximate_lon,
        priority=body.priority,
        status="NEW",
        notes=body.notes,
        demonstration=True,
        created_by=principal.user_id,
        next_action="Supervisor assignment",
    )
    session.add(item)
    session.flush()
    session.add(
        CaseStatusHistory(
            workspace_id=item.workspace_id,
            case_id=item.id,
            from_status=None,
            to_status="NEW",
            reason="Case created with a client idempotency key.",
            changed_by=principal.user_id,
        )
    )
    response = _case_payload(session, item, detail=True)
    _remember(session, principal, key, request, request_hash, response, 201)
    record_event(
        session,
        action="extension.case.create",
        resource_type="extension_case",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"case_number": item.case_number, "demonstration": True},
    )
    session.commit()
    return response


@router.get("/cases/{case_id}")
def get_case(
    case_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    return _case_payload(session, _require_case(session, principal, case_id), detail=True)


@router.post("/cases/{case_id}/assign")
def assign_case(
    case_id: uuid.UUID,
    body: AssignRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.case.assign", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_case(session, principal, case_id)
    if item.row_version != body.row_version:
        raise conflict("EXTENSION_ROW_VERSION_CONFLICT", "The case changed since it was loaded.")
    officer = session.get(User, body.officer_id)
    if officer is None:
        raise not_found("Extension officer")
    for assignment in session.scalars(
        select(CaseAssignment).where(CaseAssignment.case_id == item.id, CaseAssignment.active.is_(True))
    ).all():
        assignment.active = False
        assignment.ended_at = now()
        assignment.row_version += 1
    item.current_assignee_id = officer.id
    if body.priority:
        item.priority = body.priority
    item.next_action = "Record first observation"
    if item.status == "NEW":
        _record_transition(session, principal, item, "ASSIGNED", body.reason, request.state.correlation_id)
    else:
        item.row_version += 1
    session.add(
        CaseAssignment(
            workspace_id=item.workspace_id,
            case_id=item.id,
            officer_id=officer.id,
            assigned_by=principal.user_id,
            reason=body.reason,
        )
    )
    response = _case_payload(session, item, detail=True)
    _remember(session, principal, key, request, request_hash, response)
    record_event(
        session,
        action="extension.case.assign",
        resource_type="extension_case",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        reason=body.reason,
        after={"assignee_id": str(officer.id), "priority": item.priority},
    )
    session.commit()
    return response


@router.post("/cases/{case_id}/transition")
def transition_case(
    case_id: uuid.UUID,
    body: TransitionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_case(session, principal, case_id, update=True)
    if item.row_version != body.row_version:
        raise conflict("EXTENSION_ROW_VERSION_CONFLICT", "The case changed since it was loaded.")
    if body.target_status in {"CLOSED", "CANCELLED"}:
        assert_permission(principal, "extension.case.close", "extension-field-support")
    _record_transition(
        session,
        principal,
        item,
        body.target_status,
        body.reason,
        request.state.correlation_id,
    )
    response = _case_payload(session, item, detail=True)
    _remember(session, principal, key, request, request_hash, response)
    session.commit()
    return response


def _create_observation_record(
    session: Session,
    principal: Principal,
    case: ExtensionCase,
    body: ObservationRequest,
    correlation_id: str,
) -> Observation:
    existing = session.scalar(
        select(Observation).where(
            Observation.workspace_id == principal.active_workspace_id,
            Observation.client_uuid == body.client_uuid,
        )
    )
    if existing:
        if existing.case_id != case.id:
            raise conflict(
                "EXTENSION_CLIENT_UUID_CONFLICT",
                "The client UUID belongs to another observation.",
            )
        return existing
    if body.status == "COMPLETED" and case.status != "ASSIGNED" and case.status != "IN_OBSERVATION":
        raise conflict(
            "EXTENSION_OBSERVATION_STATE_INVALID",
            "A completed observation requires an assigned or in-observation case.",
        )
    item = Observation(
        workspace_id=principal.active_workspace_id,
        case_id=case.id,
        client_uuid=body.client_uuid,
        status=body.status,
        observed_at=body.observed_at,
        severity=body.severity,
        affected_area_ha=body.affected_area_ha,
        approximate_location=body.approximate_location,
        notes=body.notes,
        structured_json=body.structured,
        created_by=principal.user_id,
        completed_at=now() if body.status == "COMPLETED" else None,
    )
    session.add(item)
    session.flush()
    case.last_observation_at = body.observed_at
    case.next_action = "Complete evidence and begin manual field assessment"
    case.row_version += 1
    if body.status == "COMPLETED" and case.status == "ASSIGNED":
        _record_transition(
            session,
            principal,
            case,
            "IN_OBSERVATION",
            "A structured field observation was completed.",
            correlation_id,
        )
    return item


@router.post("/cases/{case_id}/observations", status_code=201)
def create_observation(
    case_id: uuid.UUID,
    body: ObservationRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.observation.create", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    case = _require_case(session, principal, case_id, update=True)
    item = _create_observation_record(session, principal, case, body, request.state.correlation_id)
    response = _observation_payload(item)
    _remember(session, principal, key, request, request_hash, response, 201)
    record_event(
        session,
        action="extension.observation.create",
        resource_type="extension_observation",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"case_id": str(case.id), "status": item.status},
    )
    session.commit()
    return response


@router.patch("/observations/{observation_id}")
def patch_observation(
    observation_id: uuid.UUID,
    body: ObservationPatchRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.observation.create", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = session.get(Observation, observation_id)
    if item is None:
        raise not_found("Observation")
    case = _require_case(session, principal, item.case_id, update=True)
    if item.status == "COMPLETED":
        raise conflict(
            "EXTENSION_OBSERVATION_IMMUTABLE",
            "A completed observation is immutable; create a new observation revision.",
        )
    if item.row_version != body.row_version:
        raise conflict("EXTENSION_ROW_VERSION_CONFLICT", "The observation changed since it was loaded.")
    item.notes = body.notes
    item.structured_json = body.structured
    item.status = body.status
    item.row_version += 1
    if body.status == "COMPLETED":
        item.completed_at = now()
        case.last_observation_at = item.observed_at
        if case.status == "ASSIGNED":
            _record_transition(
                session,
                principal,
                case,
                "IN_OBSERVATION",
                "A draft field observation was completed.",
                request.state.correlation_id,
            )
    response = _observation_payload(item)
    _remember(session, principal, key, request, request_hash, response)
    session.commit()
    return response


@router.post("/cases/{case_id}/media", status_code=201)
async def upload_media(
    case_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    observation_id: uuid.UUID | None = Query(default=None),
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.media.upload", "extension-field-support")
    case = _require_case(session, principal, case_id, update=True)
    payload = await file.read(10 * 1024 * 1024 + 1)
    if len(payload) > 10 * 1024 * 1024:
        raise PlatformError("EXTENSION_MEDIA_TOO_LARGE", "Field media is limited to 10 MB.", 413)
    media_type = file.content_type or "application/octet-stream"
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise PlatformError(
            "EXTENSION_MEDIA_TYPE_UNSUPPORTED",
            "Only JPEG, PNG and WebP demonstration images are accepted.",
            415,
        )
    digest = hashlib.sha256(payload).hexdigest()
    request_document = {
        "case_id": str(case.id),
        "observation_id": str(observation_id) if observation_id else None,
        "filename": file.filename,
        "media_type": media_type,
        "sha256": digest,
    }
    cached, request_hash = _cached(session, principal, key, request, request_document)
    if cached is not None:
        return cached
    if observation_id:
        observation = session.get(Observation, observation_id)
        if observation is None or observation.case_id != case.id:
            raise not_found("Observation")
    media_id = uuid.uuid4()
    safe_suffix = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[media_type]
    object_key = (
        f"extension/{principal.active_workspace_id}/cases/{case.id}/media/"
        f"{media_id}.{safe_suffix}"
    )
    put_bytes(object_key, payload, media_type)
    scan_bypass = APP_ENV in {"development", "test"} and ALLOW_INSECURE_DEV_FILE_SCAN
    item = MediaAsset(
        id=media_id,
        workspace_id=principal.active_workspace_id,
        case_id=case.id,
        observation_id=observation_id,
        object_key=object_key,
        filename=(file.filename or f"field-evidence.{safe_suffix}")[:500],
        media_type=media_type,
        size_bytes=len(payload),
        sha256=digest,
        scan_status="DEV_BYPASS" if scan_bypass else "PENDING",
        exif_stripped=False,
        created_by=principal.user_id,
    )
    session.add(item)
    response = {
        "id": str(item.id),
        "case_id": str(case.id),
        "filename": item.filename,
        "media_type": item.media_type,
        "size_bytes": item.size_bytes,
        "sha256": item.sha256,
        "scan_status": item.scan_status,
        "classification": item.classification,
        "exif_stripped": item.exif_stripped,
        "warning": (
            "Development scanner bypass is active; EXIF stripping is unavailable."
            if scan_bypass
            else "Media remains unavailable until the scanner marks it clean."
        ),
    }
    _remember(session, principal, key, request, request_hash, response, 201)
    record_event(
        session,
        action="extension.media.upload",
        resource_type="extension_media",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"case_id": str(case.id), "sha256": digest, "scan_status": item.scan_status},
    )
    session.commit()
    return response


@router.get("/media/{media_id}/view")
def view_media(
    media_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.media.view_sensitive", "extension-field-support")
    item = session.get(MediaAsset, media_id)
    if item is None or item.workspace_id != principal.active_workspace_id:
        raise not_found("Field media")
    _require_case(session, principal, item.case_id)
    if item.scan_status not in {"CLEAN", "DEV_BYPASS"}:
        raise conflict("EXTENSION_MEDIA_NOT_CLEAN", "The media is not available for viewing.")
    record_event(
        session,
        action="extension.media.view",
        resource_type="extension_media",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"case_id": str(item.case_id), "ttl_seconds": 900},
        severity="WARNING",
    )
    session.commit()
    return {"url": presigned_get(item.object_key), "expires_in_seconds": 900}


@router.get("/knowledge")
def list_knowledge(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.knowledge.view", "extension-field-support")
    rows = session.scalars(
        select(KnowledgeItem)
        .where(
            KnowledgeItem.workspace_id == principal.active_workspace_id,
            KnowledgeItem.status == "ACTIVE",
        )
        .order_by(KnowledgeItem.title)
    ).all()
    return {
        "items": [_knowledge_payload(session, value) for value in rows],
        "meta": {"total": len(rows)},
        "warning": "Demonstration templates with placeholder sources; not formal agronomic advice.",
    }


@router.post("/knowledge/{knowledge_id}/versions", status_code=201)
def create_knowledge_version(
    knowledge_id: uuid.UUID,
    body: KnowledgeVersionCreateRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.knowledge.edit", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    parent = session.get(KnowledgeItem, knowledge_id)
    if parent is None or parent.workspace_id != principal.active_workspace_id:
        raise not_found("Knowledge item")
    number = session.scalar(
        select(func.max(KnowledgeVersion.version_number)).where(
            KnowledgeVersion.knowledge_item_id == parent.id
        )
    ) or 0
    item = KnowledgeVersion(
        workspace_id=principal.active_workspace_id,
        knowledge_item_id=parent.id,
        version_number=number + 1,
        status="DRAFT",
        content_json=body.content,
        source_summary=body.source_summary,
        created_by=principal.user_id,
    )
    session.add(item)
    session.flush()
    response = _knowledge_payload(session, parent)
    _remember(session, principal, key, request, request_hash, response, 201)
    session.commit()
    return response


@router.post("/knowledge-versions/{version_id}/approve")
def approve_knowledge_version(
    version_id: uuid.UUID,
    body: KnowledgeApproveRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.knowledge.approve", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = session.get(KnowledgeVersion, version_id)
    if item is None or item.workspace_id != principal.active_workspace_id:
        raise not_found("Knowledge version")
    if item.status not in {"DRAFT", "UNDER_REVIEW"}:
        raise conflict("EXTENSION_KNOWLEDGE_NOT_APPROVABLE", "Only a draft or reviewed version can be approved.")
    if item.created_by == principal.user_id:
        raise conflict(
            "EXTENSION_SEPARATION_OF_DUTIES",
            "A knowledge version editor cannot approve the same version.",
        )
    if item.row_version != body.row_version:
        raise conflict("EXTENSION_ROW_VERSION_CONFLICT", "The knowledge version changed since it was loaded.")
    item.status = "DEMO_APPROVED"
    item.approved_by = principal.user_id
    item.approved_at = now()
    item.row_version += 1
    parent = session.get(KnowledgeItem, item.knowledge_item_id)
    parent.current_version_id = item.id
    parent.row_version += 1
    response = _knowledge_payload(session, parent)
    _remember(session, principal, key, request, request_hash, response)
    record_event(
        session,
        action="extension.knowledge.approve",
        resource_type="extension_knowledge_version",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        reason=body.reason,
        after={"status": item.status, "demonstration": True},
    )
    session.commit()
    return response


@router.post("/cases/{case_id}/assessments", status_code=201)
def create_assessment(
    case_id: uuid.UUID,
    body: AssessmentRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.assessment.record", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    case = _require_case(session, principal, case_id, update=True)
    if case.status not in {"IN_OBSERVATION", "IN_VERIFICATION"}:
        raise conflict(
            "EXTENSION_ASSESSMENT_STATE_INVALID",
            "Manual field assessment requires an in-observation or in-verification case.",
        )
    knowledge = session.get(KnowledgeVersion, body.knowledge_version_id)
    if (
        knowledge is None
        or knowledge.workspace_id != principal.active_workspace_id
        or knowledge.status != "DEMO_APPROVED"
    ):
        raise not_found("Approved demonstration knowledge version")
    observation_ids = set(body.supporting_observation_ids)
    valid_observation_ids = set(
        session.scalars(
            select(Observation.id).where(
                Observation.case_id == case.id,
                Observation.id.in_(observation_ids or {uuid.uuid4()}),
                Observation.status == "COMPLETED",
            )
        ).all()
    )
    if observation_ids != valid_observation_ids:
        raise conflict(
            "EXTENSION_ASSESSMENT_EVIDENCE_INVALID",
            "Supporting observations must be completed records for this case.",
        )
    item = AssessmentCandidate(
        workspace_id=principal.active_workspace_id,
        case_id=case.id,
        knowledge_version_id=knowledge.id,
        status="PROPOSED",
        supporting_observation_ids=[str(value) for value in body.supporting_observation_ids],
        missing_information=body.missing_information,
        selected_by=principal.user_id,
        review_reason=body.note,
    )
    session.add(item)
    case.assessment_json = {
        "manual": True,
        "assessment_candidate_id": str(item.id),
        "automatic_scoring": False,
    }
    case.next_action = "Complete versioned verification checklist"
    if case.status == "IN_OBSERVATION":
        _record_transition(
            session,
            principal,
            case,
            "IN_VERIFICATION",
            "Officer recorded a manual possible-cause category.",
            request.state.correlation_id,
        )
    session.flush()
    response = _assessment_payload(session, item)
    _remember(session, principal, key, request, request_hash, response, 201)
    record_event(
        session,
        action="extension.assessment.record",
        resource_type="extension_assessment",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"manual": True, "knowledge_version_id": str(knowledge.id)},
    )
    session.commit()
    return response


@router.post("/assessments/{assessment_id}/review")
def review_assessment(
    assessment_id: uuid.UUID,
    body: AssessmentReviewRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.assessment.review", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = session.get(AssessmentCandidate, assessment_id)
    if item is None or item.workspace_id != principal.active_workspace_id:
        raise not_found("Field assessment")
    if item.selected_by == principal.user_id:
        raise conflict(
            "EXTENSION_SEPARATION_OF_DUTIES",
            "The officer who selected a category cannot complete supervisor review.",
        )
    if item.status != "PROPOSED" or item.row_version != body.row_version:
        raise conflict("EXTENSION_ASSESSMENT_NOT_REVIEWABLE", "The assessment is not reviewable at this version.")
    item.status = body.decision
    item.reviewed_by = principal.user_id
    item.review_reason = body.reason
    item.row_version += 1
    response = _assessment_payload(session, item)
    _remember(session, principal, key, request, request_hash, response)
    record_event(
        session,
        action="extension.assessment.review",
        resource_type="extension_assessment",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        reason=body.reason,
        after={"decision": body.decision},
    )
    session.commit()
    return response


@router.get("/verification-templates")
def list_verification_templates(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    rows = session.scalars(
        select(VerificationTemplateVersion).where(
            VerificationTemplateVersion.workspace_id == principal.active_workspace_id,
            VerificationTemplateVersion.status == "DEMO_APPROVED",
        )
    ).all()
    return {
        "items": [
            {
                "id": str(value.id),
                "template_key": value.template_key,
                "name": value.name,
                "version_number": value.version_number,
                "status": value.status,
            }
            for value in rows
        ]
    }


@router.post("/cases/{case_id}/verifications", status_code=201)
def start_verification(
    case_id: uuid.UUID,
    body: VerificationStartRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.verification.complete", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    case = _require_case(session, principal, case_id, update=True)
    if case.status != "IN_VERIFICATION":
        raise conflict("EXTENSION_VERIFICATION_STATE_INVALID", "The case is not in verification.")
    template = session.get(VerificationTemplateVersion, body.template_version_id)
    if template is None or template.workspace_id != principal.active_workspace_id or template.status != "DEMO_APPROVED":
        raise not_found("Verification template")
    revision = session.scalar(
        select(func.max(VerificationSession.revision_number)).where(
            VerificationSession.case_id == case.id
        )
    ) or 0
    item = VerificationSession(
        workspace_id=principal.active_workspace_id,
        case_id=case.id,
        template_version_id=template.id,
        revision_number=revision + 1,
        status="DRAFT",
        created_by=principal.user_id,
    )
    session.add(item)
    session.flush()
    response = _verification_payload(session, item)
    _remember(session, principal, key, request, request_hash, response, 201)
    session.commit()
    return response


@router.patch("/verifications/{verification_id}")
def save_verification(
    verification_id: uuid.UUID,
    body: VerificationSaveRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.verification.complete", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = session.get(VerificationSession, verification_id)
    if item is None or item.workspace_id != principal.active_workspace_id:
        raise not_found("Verification session")
    case = _require_case(session, principal, item.case_id, update=True)
    if item.status == "COMPLETED":
        raise conflict(
            "EXTENSION_VERIFICATION_IMMUTABLE",
            "A completed verification is immutable; start a new revision.",
        )
    if item.row_version != body.row_version:
        raise conflict("EXTENSION_ROW_VERSION_CONFLICT", "The verification changed since it was loaded.")
    template_item_ids = set(
        session.scalars(
            select(VerificationItem.id).where(
                VerificationItem.template_version_id == item.template_version_id
            )
        ).all()
    )
    if any(value.verification_item_id not in template_item_ids for value in body.responses):
        raise conflict("EXTENSION_VERIFICATION_ITEM_INVALID", "A response does not belong to this template version.")
    for value in body.responses:
        response = session.scalar(
            select(VerificationResponse).where(
                VerificationResponse.verification_session_id == item.id,
                VerificationResponse.verification_item_id == value.verification_item_id,
            )
        )
        if response is None:
            response = VerificationResponse(
                verification_session_id=item.id,
                verification_item_id=value.verification_item_id,
            )
            session.add(response)
        response.response_json = {"value": value.value}
        response.evidence_note = value.evidence_note
    session.flush()
    item.row_version += 1
    if body.complete:
        required_ids = set(
            session.scalars(
                select(VerificationItem.id).where(
                    VerificationItem.template_version_id == item.template_version_id,
                    VerificationItem.required.is_(True),
                )
            ).all()
        )
        answered_ids = set(
            session.scalars(
                select(VerificationResponse.verification_item_id).where(
                    VerificationResponse.verification_session_id == item.id
                )
            ).all()
        )
        if not required_ids <= answered_ids:
            raise conflict(
                "EXTENSION_VERIFICATION_INCOMPLETE",
                "Every required checklist item must have a structured response.",
                missing=[str(value) for value in sorted(required_ids - answered_ids, key=str)],
            )
        item.status = "COMPLETED"
        item.completed_at = now()
        case.next_action = "Create an activity plan"
        record_event(
            session,
            action="extension.verification.complete",
            resource_type="extension_verification",
            resource_id=item.id,
            outcome="success",
            correlation_id=request.state.correlation_id,
            actor_id=principal.user_id,
            workspace_id=principal.active_workspace_id,
            after={"case_id": str(case.id), "revision": item.revision_number},
        )
    response_payload = _verification_payload(session, item)
    _remember(session, principal, key, request, request_hash, response_payload)
    session.commit()
    return response_payload


@router.get("/activities")
def list_activities(
    status: str | None = None,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    query = select(ActivityPlan).where(
        ActivityPlan.workspace_id == principal.active_workspace_id
    )
    if status:
        query = query.where(ActivityPlan.status == status.upper())
    rows = session.scalars(query.order_by(ActivityPlan.due_date)).all()
    visible = [
        value
        for value in rows
        if value.case_id is None
        or _can_view_case(principal, session.get(ExtensionCase, value.case_id))
    ]
    return {"items": [_activity_payload(session, value) for value in visible], "meta": {"total": len(visible)}}


@router.post("/activities", status_code=201)
def create_activity(
    body: ActivityCreateRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.activity.plan", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    case = _require_case(session, principal, body.case_id, update=True) if body.case_id else None
    if case and case.status != "IN_VERIFICATION":
        raise conflict("EXTENSION_ACTIVITY_STATE_INVALID", "A case activity plan follows verification.")
    item = ActivityPlan(
        workspace_id=principal.active_workspace_id,
        case_id=case.id if case else None,
        activity_type=body.activity_type,
        objective=body.objective,
        participant_count=body.participant_count,
        responsible_officer_id=body.responsible_officer_id,
        due_date=body.due_date,
        status="PENDING_APPROVAL" if body.submit_for_approval else "DRAFT",
        created_by=principal.user_id,
    )
    session.add(item)
    session.flush()
    for ordinal, description in enumerate(body.steps, start=1):
        session.add(
            ActivityStep(
                activity_plan_id=item.id,
                ordinal=ordinal,
                description=description,
                responsible_officer_id=body.responsible_officer_id,
                due_date=body.due_date,
            )
        )
    if case:
        _record_transition(
            session,
            principal,
            case,
            "ACTION_PLANNED",
            "A structured activity plan was created after verification.",
            request.state.correlation_id,
        )
        case.next_action = "Supervisor activity approval"
    session.flush()
    response = _activity_payload(session, item)
    _remember(session, principal, key, request, request_hash, response, 201)
    session.commit()
    return response


@router.post("/activities/{activity_id}/approval")
def approve_activity(
    activity_id: uuid.UUID,
    body: ActivityApprovalRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.activity.approve", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = session.get(ActivityPlan, activity_id)
    if item is None or item.workspace_id != principal.active_workspace_id:
        raise not_found("Activity plan")
    if item.created_by == principal.user_id:
        raise conflict(
            "EXTENSION_SEPARATION_OF_DUTIES",
            "The activity creator cannot approve the same plan.",
        )
    if item.status != "PENDING_APPROVAL" or item.row_version != body.row_version:
        raise conflict("EXTENSION_ACTIVITY_NOT_APPROVABLE", "The activity is not approvable at this version.")
    item.status = "APPROVED" if body.decision == "APPROVE" else "REJECTED"
    item.approved_by = principal.user_id if body.decision == "APPROVE" else None
    item.approved_at = now() if body.decision == "APPROVE" else None
    item.row_version += 1
    response = _activity_payload(session, item)
    _remember(session, principal, key, request, request_hash, response)
    record_event(
        session,
        action="extension.activity.approve",
        resource_type="extension_activity",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        reason=body.reason,
        after={"status": item.status},
    )
    session.commit()
    return response


@router.post("/cases/{case_id}/follow-ups", status_code=201)
def create_follow_up(
    case_id: uuid.UUID,
    body: FollowUpCreateRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.followup.manage", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    case = _require_case(session, principal, case_id, update=True)
    if case.status != "ACTION_PLANNED":
        raise conflict("EXTENSION_FOLLOWUP_STATE_INVALID", "A follow-up requires an action-planned case.")
    if body.activity_plan_id:
        plan = session.get(ActivityPlan, body.activity_plan_id)
        if plan is None or plan.case_id != case.id or plan.status != "APPROVED":
            raise not_found("Approved activity plan")
    item = FollowUp(
        workspace_id=principal.active_workspace_id,
        case_id=case.id,
        activity_plan_id=body.activity_plan_id,
        due_date=body.due_date,
        status="OPEN",
        objective=body.objective,
        created_by=principal.user_id,
    )
    session.add(item)
    _record_transition(
        session,
        principal,
        case,
        "FOLLOW_UP",
        "A dated follow-up was scheduled.",
        request.state.correlation_id,
    )
    case.next_action = f"Follow-up due {body.due_date.isoformat()}"
    session.flush()
    response = _follow_up_payload(item)
    _remember(session, principal, key, request, request_hash, response, 201)
    session.commit()
    return response


@router.post("/follow-ups/{follow_up_id}/complete")
def complete_follow_up(
    follow_up_id: uuid.UUID,
    body: FollowUpCompleteRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.followup.manage", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = session.get(FollowUp, follow_up_id)
    if item is None or item.workspace_id != principal.active_workspace_id:
        raise not_found("Follow-up")
    case = _require_case(session, principal, item.case_id, update=True)
    if item.status != "OPEN" or item.row_version != body.row_version:
        raise conflict("EXTENSION_FOLLOWUP_NOT_OPEN", "The follow-up is not open at this version.")
    item.status = "COMPLETED"
    item.outcome = body.outcome
    item.completed_at = now()
    item.row_version += 1
    case.next_action = "Supervisor may close the case after reviewing closure evidence"
    response = _follow_up_payload(item)
    _remember(session, principal, key, request, request_hash, response)
    record_event(
        session,
        action="extension.followup.complete",
        resource_type="extension_follow_up",
        resource_id=item.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"case_id": str(case.id)},
    )
    session.commit()
    return response


@router.get("/supervision")
def supervision(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "apps.extension.supervise", "extension-field-support")
    cases = session.scalars(
        select(ExtensionCase).where(
            ExtensionCase.workspace_id == principal.active_workspace_id
        )
    ).all()
    workload_rows = session.execute(
        select(User, func.count(ExtensionCase.id))
        .join(ExtensionCase, ExtensionCase.current_assignee_id == User.id)
        .where(
            ExtensionCase.workspace_id == principal.active_workspace_id,
            ExtensionCase.status.notin_(["CLOSED", "CANCELLED"]),
        )
        .group_by(User.id)
        .order_by(User.display_name)
    ).all()
    overdue = session.scalars(
        select(FollowUp).where(
            FollowUp.workspace_id == principal.active_workspace_id,
            FollowUp.status == "OPEN",
            FollowUp.due_date < date.today(),
        )
    ).all()
    pending = session.scalars(
        select(ActivityPlan).where(
            ActivityPlan.workspace_id == principal.active_workspace_id,
            ActivityPlan.status == "PENDING_APPROVAL",
        )
    ).all()
    return {
        "unassigned_cases": [_case_payload(session, value) for value in cases if value.current_assignee_id is None and value.status == "NEW"],
        "team_workload": [
            {"officer_id": str(user.id), "display_name": user.display_name, "active_cases": count}
            for user, count in workload_rows
        ],
        "overdue_follow_ups": [_follow_up_payload(value) for value in overdue],
        "pending_activity_approvals": [_activity_payload(session, value) for value in pending],
        "case_map_path": "/apps/extension-field-support/map",
    }


@router.get("/sync")
def sync_status(principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    _enter(principal)
    return {
        "server": "online",
        "accepted_mutations": ["observation.create"],
        "idempotency": "client_uuid_and_idempotency_key",
        "limitations": [
            "Drafts are stored in session storage on this demonstration device.",
            "Sensitive media is never cached by the service worker.",
            "Full offline conflict resolution is not implemented.",
        ],
    }


@router.post("/sync")
def sync_mutations(
    body: SyncRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "extension.observation.create", "extension-field-support")
    cached, request_hash = _cached(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    acknowledgements: list[dict[str, Any]] = []
    for mutation in body.items:
        case = _require_case(session, principal, mutation.case_id, update=True)
        payload = mutation.payload.model_copy(update={"client_uuid": mutation.client_uuid})
        existing = session.scalar(
            select(Observation).where(
                Observation.workspace_id == principal.active_workspace_id,
                Observation.client_uuid == mutation.client_uuid,
            )
        )
        item = existing or _create_observation_record(
            session,
            principal,
            case,
            payload,
            request.state.correlation_id,
        )
        acknowledgements.append(
            {
                "client_uuid": str(mutation.client_uuid),
                "server_id": str(item.id),
                "status": "DUPLICATE_ACKNOWLEDGED" if existing else "CREATED",
            }
        )
    response = {"items": acknowledgements, "meta": {"processed": len(acknowledgements)}}
    _remember(session, principal, key, request, request_hash, response)
    record_event(
        session,
        action="extension.sync.process",
        resource_type="extension_sync_batch",
        resource_id=key,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"processed": len(acknowledgements)},
    )
    session.commit()
    return response
