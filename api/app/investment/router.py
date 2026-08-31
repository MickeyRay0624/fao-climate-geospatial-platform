from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit_service import record_event
from app.authorization import assert_permission, can_access_dataset
from app.catalog import INDICATORS
from app.config import DEMO_DISCLAIMER
from app.database import get_session
from app.errors import PlatformError, conflict, forbidden, not_found
from app.identity import Principal, get_current_principal
from app.investment.canonical import checksum_json, execution_metadata
from app.investment.constants import (
    INDICATOR_CODES,
    METHOD_IMPLEMENTATION_KEY,
    WORKER_TASK_VERSION,
)
from app.investment.engine import normalise_weights
from app.investment.metrics import prometheus_text
from app.investment.schemas import (
    CancelRunRequest,
    CloneInputSetRequest,
    CreateComparisonRequest,
    CreateExportRequest,
    CreateInputSetRequest,
    CreateMethodRequest,
    CreateMethodVersionRequest,
    CreateRunRequest,
    CreateScenarioRequest,
    InputMemberRequest,
    PatchInputMemberRequest,
    PatchInputSetRequest,
    PatchMethodVersionRequest,
    PatchScenarioRequest,
    RetireRequest,
    WorkflowRequest,
)
from app.investment.service import (
    asset_payloads,
    audit_payload,
    can_access_run,
    canonical_input_set,
    comparison_payload,
    create_comparison,
    create_run_inputs,
    input_set_payload,
    lineage_payload,
    method_checksum,
    method_version_payload,
    require_run_access,
    result_records,
    run_payload,
    scenario_checksum,
    scenario_payload,
    stable_output_id,
    validate_input_set,
    validate_method_spec,
    validate_scenario_parameters,
)
from app.investment.tasks import run_prioritisation
from app.platform_models import (
    CatalogAsset,
    CatalogDataset,
    CatalogDatasetVersion,
    Group,
    IdempotencyRecord,
    InvestmentAnalysisInputMember,
    InvestmentAnalysisInputSet,
    InvestmentAnalysisRun,
    InvestmentIndicatorDefinition,
    InvestmentMethodDefinition,
    InvestmentMethodVersion,
    InvestmentPriorityResult,
    InvestmentRunComparison,
    InvestmentScenario,
    InvestmentScenarioParameter,
    JobStep,
    ProcessingJob,
    QualityProfile,
    Representation,
    ReviewRequest,
)


router = APIRouter(
    prefix="/api/apps/investment-prioritisation/v1",
    tags=["Investment Prioritisation"],
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _enter(principal: Principal) -> None:
    assert_permission(principal, "apps.investment.use", "investment-prioritisation")


def require_idempotency_key(
    value: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if not value or len(value) < 8:
        raise PlatformError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "Investment mutations require an Idempotency-Key header of at least 8 characters.",
            400,
        )
    return value[:255]


def _cached_mutation(
    session: Session,
    principal: Principal,
    key: str,
    request: Request,
    body: Any,
) -> tuple[dict[str, Any] | None, str]:
    request_hash = checksum_json(body)
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
    stored_hash = row.response_json.get("request_hash")
    if stored_hash != request_hash:
        raise conflict(
            "IDEMPOTENCY_KEY_CONFLICT",
            "The idempotency key was already used with a different canonical payload.",
        )
    return row.response_json.get("response", {}), request_hash


def _remember_mutation(
    session: Session,
    principal: Principal,
    key: str,
    request: Request,
    request_hash: str,
    response: dict[str, Any],
    *,
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


def _page(query, session: Session, page: int, page_size: int):
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.offset((page - 1) * page_size).limit(page_size)
    ).all()
    return rows, {"page": page, "page_size": page_size, "total": total}


def _input_access(
    session: Session, principal: Principal, item: InvestmentAnalysisInputSet | None
) -> bool:
    if item is None or item.workspace_id != principal.active_workspace_id:
        return False
    members = session.scalars(
        select(InvestmentAnalysisInputMember).where(
            InvestmentAnalysisInputMember.input_set_id == item.id
        )
    ).all()
    for member in members:
        version = session.get(CatalogDatasetVersion, member.dataset_version_id)
        dataset = session.get(CatalogDataset, version.dataset_id) if version else None
        if not dataset or not can_access_dataset(
            session, principal, dataset, "dataset.view_metadata"
        ):
            return False
    return True


def _require_input(
    session: Session, principal: Principal, input_set_id: uuid.UUID
) -> InvestmentAnalysisInputSet:
    item = session.get(InvestmentAnalysisInputSet, input_set_id)
    if not _input_access(session, principal, item):
        raise not_found("Input set")
    return item


def _draft_input(item: InvestmentAnalysisInputSet) -> None:
    if item.status not in {"DRAFT", "VALIDATED"}:
        raise conflict(
            "INPUT_SET_IMMUTABLE",
            "Locked or retired input sets cannot be modified; clone it first.",
            status=item.status,
        )


def _check_version(actual: int, supplied: int) -> None:
    if actual != supplied:
        raise conflict(
            "OPTIMISTIC_LOCK_CONFLICT",
            "The resource changed since it was loaded.",
            current_row_version=actual,
        )


def _validate_member_reference(
    session: Session, principal: Principal, body: InputMemberRequest
) -> None:
    version = session.get(CatalogDatasetVersion, body.dataset_version_id)
    representation = session.get(Representation, body.representation_id)
    dataset = session.get(CatalogDataset, version.dataset_id) if version else None
    if (
        version is None
        or representation is None
        or representation.dataset_version_id != version.id
        or dataset is None
        or not can_access_dataset(session, principal, dataset, "dataset.download")
    ):
        raise not_found("Dataset representation")


@router.get("/overview")
def overview(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    workspace = principal.active_workspace_id
    counts = {
        "locked_input_sets": session.scalar(
            select(func.count(InvestmentAnalysisInputSet.id)).where(
                InvestmentAnalysisInputSet.workspace_id == workspace,
                InvestmentAnalysisInputSet.status == "LOCKED",
            )
        )
        or 0,
        "approved_scenarios": session.scalar(
            select(func.count(InvestmentScenario.id)).where(
                InvestmentScenario.workspace_id == workspace,
                InvestmentScenario.state == "APPROVED",
            )
        )
        or 0,
        "runs": session.scalar(
            select(func.count(InvestmentAnalysisRun.id)).where(
                InvestmentAnalysisRun.workspace_id == workspace
            )
        )
        or 0,
    }
    recent = session.scalars(
        select(InvestmentAnalysisRun)
        .where(InvestmentAnalysisRun.workspace_id == workspace)
        .order_by(InvestmentAnalysisRun.requested_at.desc())
        .limit(5)
    ).all()
    return {
        "module": "investment-prioritisation",
        "phase": "2A",
        "native_write_authority": "investment.*",
        "counts": counts,
        "recent_runs": [run_payload(session, item) for item in recent if can_access_run(session, principal, item)],
        "synthetic": True,
        "business_validation": "not_performed",
        "disclaimer": DEMO_DISCLAIMER,
    }


@router.get("/capabilities")
def capabilities(principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    _enter(principal)
    codes = [
        "investment.input_set.create",
        "investment.input_set.lock",
        "investment.run.create",
        "investment.run.view",
        "investment.run.cancel",
        "investment.run.export",
        "investment.run.compare",
        "investment.method.edit",
        "investment.method.approve",
        "investment.scenario.edit",
        "investment.scenario.approve",
        "investment.result.submit_review",
    ]
    return {
        "workspace_id": str(principal.active_workspace_id),
        "capabilities": {code: code in principal.effective_permissions for code in codes},
        "roles": sorted(principal.role_keys),
        "asynchronous_runs": True,
        "legacy_writes": False,
    }


@router.get("/data-profiles")
def data_profiles(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    profiles = session.scalars(
        select(QualityProfile)
        .where(
            QualityProfile.profile_key.in_(
                [
                    "analysis-ready-priority-bundle",
                    "administrative-boundary",
                    "normalised-indicator-layer",
                    "priority-ranking",
                ]
            )
        )
        .order_by(QualityProfile.profile_key)
    ).all()
    indicators = session.scalars(
        select(InvestmentIndicatorDefinition).order_by(InvestmentIndicatorDefinition.code)
    ).all()
    return {
        "profiles": [
            {
                "key": f"{item.profile_key}@{item.profile_version}",
                "data_kind": item.data_kind,
                "active": item.active,
                "rules": item.rules_json,
            }
            for item in profiles
        ],
        "indicators": [
            {
                "code": item.code,
                "title": item.title,
                "unit": item.unit,
                "direction": item.direction,
                "expected_profile": item.expected_profile,
            }
            for item in indicators
        ],
    }


@router.get("/input-sets")
def list_input_sets(
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    query = select(InvestmentAnalysisInputSet).where(
        InvestmentAnalysisInputSet.workspace_id == principal.active_workspace_id
    )
    if status:
        query = query.where(InvestmentAnalysisInputSet.status == status.upper())
    query = query.order_by(InvestmentAnalysisInputSet.created_at.desc())
    rows, meta = _page(query, session, page, page_size)
    visible = [item for item in rows if _input_access(session, principal, item)]
    return {"items": [input_set_payload(session, item) for item in visible], "meta": meta}


@router.post("/input-sets", status_code=201)
def create_input_set(
    body: CreateInputSetRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.create", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = InvestmentAnalysisInputSet(
        workspace_id=principal.active_workspace_id,
        name=body.name,
        label=body.label,
        profile_mode=body.profile_mode,
        status="DRAFT",
        study_area_ref=body.study_area_ref,
        run_mode_compatibility=body.run_mode_compatibility,
        strictest_classification="FAO_INTERNAL",
        created_by=principal.user_id,
    )
    session.add(item)
    session.flush()
    response = input_set_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response, status=201)
    record_event(
        session, action="investment.input_set.create", resource_type="analysis_input_set",
        resource_id=item.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        after={"profile_mode": item.profile_mode},
    )
    session.commit()
    return response


@router.get("/input-sets/{input_set_id}")
def get_input_set(
    input_set_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    return input_set_payload(session, _require_input(session, principal, input_set_id))


@router.patch("/input-sets/{input_set_id}")
def patch_input_set(
    input_set_id: uuid.UUID,
    body: PatchInputSetRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.create", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_input(session, principal, input_set_id)
    _draft_input(item)
    _check_version(item.row_version, body.row_version)
    for field in ("name", "label", "study_area_ref"):
        value = getattr(body, field)
        if value is not None:
            setattr(item, field, value)
    item.status = "DRAFT"
    item.readiness_result = {}
    item.checksum = None
    item.row_version += 1
    session.flush()
    response = input_set_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


def _member_from_body(
    input_set_id: uuid.UUID, body: InputMemberRequest, *, member_id: uuid.UUID | None = None
) -> InvestmentAnalysisInputMember:
    return InvestmentAnalysisInputMember(
        id=member_id or uuid.uuid4(),
        input_set_id=input_set_id,
        dataset_version_id=body.dataset_version_id,
        representation_id=body.representation_id,
        input_role=body.input_role,
        indicator_code=body.indicator_code,
        join_key=body.join_key,
        value_field=body.value_field,
        geometry_field=body.geometry_field,
        unit=body.unit,
        direction=body.direction,
        time_coverage=body.time_coverage,
        required=body.required,
        transform_config=body.transform_config,
        ordinal=body.ordinal,
    )


@router.post("/input-sets/{input_set_id}/members", status_code=201)
def add_input_member(
    input_set_id: uuid.UUID,
    body: InputMemberRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.create", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_input(session, principal, input_set_id)
    _draft_input(item)
    _validate_member_reference(session, principal, body)
    member = _member_from_body(item.id, body)
    session.add(member)
    item.status = "DRAFT"
    item.readiness_result = {}
    item.checksum = None
    item.row_version += 1
    session.flush()
    response = input_set_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response, status=201)
    session.commit()
    return response


@router.patch("/input-sets/{input_set_id}/members/{member_id}")
def patch_input_member(
    input_set_id: uuid.UUID,
    member_id: uuid.UUID,
    body: PatchInputMemberRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.create", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_input(session, principal, input_set_id)
    _draft_input(item)
    _check_version(item.row_version, body.row_version)
    member = session.get(InvestmentAnalysisInputMember, member_id)
    if member is None or member.input_set_id != item.id:
        raise not_found("Input member")
    _validate_member_reference(session, principal, body)
    replacement = _member_from_body(item.id, body, member_id=member.id)
    for field in (
        "dataset_version_id", "representation_id", "input_role", "indicator_code", "join_key",
        "value_field", "geometry_field", "unit", "direction", "time_coverage", "required",
        "transform_config", "ordinal",
    ):
        setattr(member, field, getattr(replacement, field))
    item.status = "DRAFT"
    item.readiness_result = {}
    item.checksum = None
    item.row_version += 1
    session.flush()
    response = input_set_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


@router.delete("/input-sets/{input_set_id}/members/{member_id}")
def delete_input_member(
    input_set_id: uuid.UUID,
    member_id: uuid.UUID,
    request: Request,
    row_version: int = Query(ge=1),
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.create", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, {"row_version": row_version})
    if cached is not None:
        return cached
    item = _require_input(session, principal, input_set_id)
    _draft_input(item)
    _check_version(item.row_version, row_version)
    member = session.get(InvestmentAnalysisInputMember, member_id)
    if member is None or member.input_set_id != item.id:
        raise not_found("Input member")
    session.delete(member)
    item.status = "DRAFT"
    item.readiness_result = {}
    item.checksum = None
    item.row_version += 1
    session.flush()
    response = input_set_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


@router.post("/input-sets/{input_set_id}/validate")
def validate_input_set_endpoint(
    input_set_id: uuid.UUID,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.create", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, {})
    if cached is not None:
        return cached
    item = _require_input(session, principal, input_set_id)
    _draft_input(item)
    readiness = validate_input_set(session, item, principal, require_published=False)
    item.readiness_result = readiness
    item.warnings_json = readiness["warnings"]
    item.strictest_classification = readiness["strictest_classification"]
    item.status = "VALIDATED" if readiness["ready"] else "DRAFT"
    item.row_version += 1
    response = {"input_set": input_set_payload(session, item), "readiness": readiness}
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


@router.post("/input-sets/{input_set_id}/lock")
def lock_input_set(
    input_set_id: uuid.UUID,
    body: WorkflowRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.lock", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_input(session, principal, input_set_id)
    _draft_input(item)
    _check_version(item.row_version, body.row_version)
    readiness = validate_input_set(session, item, principal, require_published=True)
    if not readiness["ready"]:
        raise conflict("INPUT_SET_NOT_READY", "The input set cannot be locked.", errors=readiness["errors"])
    members = session.scalars(
        select(InvestmentAnalysisInputMember)
        .where(InvestmentAnalysisInputMember.input_set_id == item.id)
        .order_by(InvestmentAnalysisInputMember.ordinal)
    ).all()
    item.readiness_result = readiness
    item.warnings_json = readiness["warnings"]
    item.strictest_classification = readiness["strictest_classification"]
    item.checksum = checksum_json(canonical_input_set(item, list(members)))
    item.status = "LOCKED"
    item.locked_by = principal.user_id
    item.locked_at = now()
    item.row_version += 1
    session.flush()
    response = input_set_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    record_event(
        session, action="investment.input_set.lock", resource_type="analysis_input_set",
        resource_id=item.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        reason=body.reason, after={"checksum": item.checksum},
    )
    session.commit()
    return response


@router.post("/input-sets/{input_set_id}/clone", status_code=201)
def clone_input_set(
    input_set_id: uuid.UUID,
    body: CloneInputSetRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.create", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    source = _require_input(session, principal, input_set_id)
    clone = InvestmentAnalysisInputSet(
        workspace_id=source.workspace_id, name=body.name, label=body.label,
        profile_mode=source.profile_mode, status="DRAFT", study_area_ref=source.study_area_ref,
        run_mode_compatibility=source.run_mode_compatibility,
        strictest_classification=source.strictest_classification, created_by=principal.user_id,
    )
    session.add(clone)
    session.flush()
    members = session.scalars(
        select(InvestmentAnalysisInputMember)
        .where(InvestmentAnalysisInputMember.input_set_id == source.id)
        .order_by(InvestmentAnalysisInputMember.ordinal)
    ).all()
    for member in members:
        session.add(
            InvestmentAnalysisInputMember(
                input_set_id=clone.id, dataset_version_id=member.dataset_version_id,
                representation_id=member.representation_id, input_role=member.input_role,
                indicator_code=member.indicator_code, join_key=member.join_key,
                value_field=member.value_field, geometry_field=member.geometry_field,
                unit=member.unit, direction=member.direction, time_coverage=member.time_coverage,
                required=member.required, transform_config=member.transform_config, ordinal=member.ordinal,
            )
        )
    session.flush()
    response = input_set_payload(session, clone)
    _remember_mutation(session, principal, key, request, request_hash, response, status=201)
    session.commit()
    return response


@router.post("/input-sets/{input_set_id}/retire")
def retire_input_set(
    input_set_id: uuid.UUID,
    body: RetireRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.input_set.lock", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_input(session, principal, input_set_id)
    if item.status != "LOCKED":
        raise conflict("INPUT_SET_NOT_RETIRABLE", "Only a locked input set can be retired.")
    _check_version(item.row_version, body.row_version)
    item.status = "RETIRED"
    item.retired_by = principal.user_id
    item.retired_at = now()
    session.flush()
    response = input_set_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


def _method_payload(session: Session, item: InvestmentMethodDefinition) -> dict[str, Any]:
    versions = session.scalars(
        select(InvestmentMethodVersion)
        .where(InvestmentMethodVersion.method_id == item.id)
        .order_by(InvestmentMethodVersion.created_at.desc())
    ).all()
    return {
        "id": str(item.id),
        "method_key": item.method_key,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "owner_group_id": str(item.owner_group_id) if item.owner_group_id else None,
        "row_version": item.row_version,
        "versions": [method_version_payload(session, version) for version in versions],
    }


def _require_method_version(
    session: Session, method_version_id: uuid.UUID
) -> InvestmentMethodVersion:
    item = session.get(InvestmentMethodVersion, method_version_id)
    if item is None:
        raise not_found("Method version")
    return item


def _method_draft(item: InvestmentMethodVersion) -> None:
    if item.state != "DRAFT":
        raise conflict(
            "METHOD_VERSION_IMMUTABLE",
            "Only a draft method version can be edited.",
            state=item.state,
        )


@router.get("/methods")
def list_methods(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    rows, meta = _page(
        select(InvestmentMethodDefinition).order_by(InvestmentMethodDefinition.method_key),
        session,
        page,
        page_size,
    )
    return {"items": [_method_payload(session, item) for item in rows], "meta": meta}


@router.get("/methods/{method_id}")
def get_method(
    method_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    item = session.get(InvestmentMethodDefinition, method_id)
    if item is None:
        raise not_found("Method")
    return _method_payload(session, item)


@router.post("/methods", status_code=201)
def create_method(
    body: CreateMethodRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.method.edit", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    if session.scalar(
        select(InvestmentMethodDefinition.id).where(
            InvestmentMethodDefinition.method_key == body.method_key
        )
    ):
        raise conflict("METHOD_KEY_EXISTS", "The method key is already in use.")
    owner_group = session.scalar(
        select(Group).where(
            Group.workspace_id == principal.active_workspace_id,
            Group.slug == "investment-method-board",
        )
    )
    item = InvestmentMethodDefinition(
        method_key=body.method_key,
        name=body.name,
        description=body.description,
        owner_group_id=owner_group.id if owner_group else None,
        status="ACTIVE",
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    session.add(item)
    session.flush()
    response = _method_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response, status=201)
    session.commit()
    return response


@router.post("/methods/{method_id}/versions", status_code=201)
def create_method_version(
    method_id: uuid.UUID,
    body: CreateMethodVersionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.method.edit", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    method = session.get(InvestmentMethodDefinition, method_id)
    if method is None:
        raise not_found("Method")
    if body.implementation_key != METHOD_IMPLEMENTATION_KEY:
        raise conflict(
            "METHOD_IMPLEMENTATION_UNSUPPORTED",
            "Phase 2A supports only the native preserved scoring implementation.",
        )
    validate_method_spec(body.specification)
    if session.scalar(
        select(InvestmentMethodVersion.id).where(
            InvestmentMethodVersion.method_id == method.id,
            InvestmentMethodVersion.version_label == body.version_label,
        )
    ):
        raise conflict("METHOD_VERSION_EXISTS", "The method version already exists.")
    item = InvestmentMethodVersion(
        method_id=method.id,
        version_label=body.version_label,
        state="DRAFT",
        specification_json=body.specification,
        checksum=method_checksum(body.specification),
        implementation_key=body.implementation_key,
        code_ref=body.code_ref,
        container_metadata=body.container_metadata,
        validation_evidence=body.validation_evidence,
        disclaimer=body.disclaimer,
        created_by=principal.user_id,
    )
    session.add(item)
    session.flush()
    response = method_version_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response, status=201)
    session.commit()
    return response


@router.get("/method-versions/{method_version_id}")
def get_method_version(
    method_version_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    return method_version_payload(session, _require_method_version(session, method_version_id))


@router.patch("/method-versions/{method_version_id}")
def patch_method_version(
    method_version_id: uuid.UUID,
    body: PatchMethodVersionRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.method.edit", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_method_version(session, method_version_id)
    _method_draft(item)
    _check_version(item.row_version, body.row_version)
    if body.specification is not None:
        validate_method_spec(body.specification)
        item.specification_json = body.specification
        item.checksum = method_checksum(body.specification)
    if body.validation_evidence is not None:
        item.validation_evidence = body.validation_evidence
    if body.disclaimer is not None:
        item.disclaimer = body.disclaimer
    item.row_version += 1
    session.flush()
    response = method_version_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


def _method_transition(
    session: Session,
    principal: Principal,
    item: InvestmentMethodVersion,
    action: str,
    body: WorkflowRequest,
    request: Request,
) -> None:
    _check_version(item.row_version, body.row_version)
    if action == "submit":
        assert_permission(principal, "investment.method.edit", "investment-prioritisation")
        _method_draft(item)
        validate_method_spec(item.specification_json)
        item.state = "UNDER_REVIEW"
        item.submitted_by = principal.user_id
        item.submitted_at = now()
    elif action == "approve":
        assert_permission(principal, "investment.method.approve", "investment-prioritisation")
        if item.state != "UNDER_REVIEW":
            raise conflict("METHOD_NOT_APPROVABLE", "The method version is not under review.")
        if item.created_by == principal.user_id:
            raise conflict("SEPARATION_OF_DUTIES", "A method version creator cannot approve it.")
        item.state = "APPROVED"
        item.approved_by = principal.user_id
        item.approved_at = now()
    else:
        assert_permission(principal, "investment.method.approve", "investment-prioritisation")
        if item.state != "APPROVED":
            raise conflict("METHOD_NOT_RETIRABLE", "Only an approved method version can be retired.")
        item.state = "RETIRED"
        item.retired_at = now()
    record_event(
        session, action=f"investment.method.{action}", resource_type="method_version",
        resource_id=item.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        reason=body.reason, after={"state": item.state},
    )


def _method_workflow_endpoint(
    method_version_id: uuid.UUID,
    body: WorkflowRequest,
    request: Request,
    key: str,
    principal: Principal,
    session: Session,
    action: str,
) -> dict[str, Any]:
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_method_version(session, method_version_id)
    _method_transition(session, principal, item, action, body, request)
    session.flush()
    session.refresh(item)
    response = method_version_payload(session, item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


@router.post("/method-versions/{method_version_id}/submit")
def submit_method_version(
    method_version_id: uuid.UUID, body: WorkflowRequest, request: Request,
    key: str = Depends(require_idempotency_key), principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _method_workflow_endpoint(method_version_id, body, request, key, principal, session, "submit")


@router.post("/method-versions/{method_version_id}/approve")
def approve_method_version(
    method_version_id: uuid.UUID, body: WorkflowRequest, request: Request,
    key: str = Depends(require_idempotency_key), principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _method_workflow_endpoint(method_version_id, body, request, key, principal, session, "approve")


@router.post("/method-versions/{method_version_id}/retire")
def retire_method_version(
    method_version_id: uuid.UUID, body: WorkflowRequest, request: Request,
    key: str = Depends(require_idempotency_key), principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _method_workflow_endpoint(method_version_id, body, request, key, principal, session, "retire")


def _sync_scenario_parameters(session: Session, item: InvestmentScenario) -> None:
    session.execute(
        delete(InvestmentScenarioParameter).where(
            InvestmentScenarioParameter.scenario_id == item.id
        )
    )
    weights = item.parameters_json["weights"]
    for ordinal, code in enumerate(INDICATOR_CODES):
        session.add(
            InvestmentScenarioParameter(
                scenario_id=item.id,
                parameter_key=code,
                numeric_value=float(weights[code]),
                ordinal=ordinal,
            )
        )
    session.add(
        InvestmentScenarioParameter(
            scenario_id=item.id,
            parameter_key="min_rice_area_ha",
            numeric_value=float(item.parameters_json["min_rice_area_ha"]),
            ordinal=len(INDICATOR_CODES),
        )
    )


def _scenario_draft(item: InvestmentScenario) -> None:
    if item.state != "DRAFT":
        raise conflict("SCENARIO_IMMUTABLE", "Only a draft scenario can be edited.", state=item.state)


def _require_scenario(
    session: Session, principal: Principal, scenario_id: uuid.UUID
) -> InvestmentScenario:
    item = session.get(InvestmentScenario, scenario_id)
    if item is None or item.workspace_id != principal.active_workspace_id:
        raise not_found("Scenario")
    return item


@router.get("/scenarios")
def list_scenarios(
    state: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    query = select(InvestmentScenario).where(
        InvestmentScenario.workspace_id == principal.active_workspace_id
    )
    if state:
        query = query.where(InvestmentScenario.state == state.upper())
    rows, meta = _page(query.order_by(InvestmentScenario.name, InvestmentScenario.version_label), session, page, page_size)
    return {"items": [scenario_payload(item) for item in rows], "meta": meta}


@router.get("/scenarios/{scenario_id}")
def get_scenario(
    scenario_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _enter(principal)
    return scenario_payload(_require_scenario(session, principal, scenario_id))


@router.post("/scenarios", status_code=201)
def create_scenario(
    body: CreateScenarioRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.scenario.edit", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    method = _require_method_version(session, body.method_version_id)
    if method.state != "APPROVED":
        raise conflict("APPROVED_METHOD_REQUIRED", "A scenario must bind an approved method version.")
    parameters = validate_scenario_parameters(body.parameters)
    if session.scalar(
        select(InvestmentScenario.id).where(
            InvestmentScenario.workspace_id == principal.active_workspace_id,
            InvestmentScenario.scenario_key == body.scenario_key,
            InvestmentScenario.version_label == body.version_label,
        )
    ):
        raise conflict("SCENARIO_VERSION_EXISTS", "The scenario version already exists.")
    item = InvestmentScenario(
        workspace_id=principal.active_workspace_id, scenario_key=body.scenario_key,
        version_label=body.version_label, name=body.name, description=body.description,
        method_version_id=method.id, state="DRAFT", parameters_json=parameters,
        checksum=scenario_checksum(parameters), disclaimer=body.disclaimer,
        created_by=principal.user_id,
    )
    session.add(item)
    session.flush()
    _sync_scenario_parameters(session, item)
    session.flush()
    response = scenario_payload(item)
    _remember_mutation(session, principal, key, request, request_hash, response, status=201)
    session.commit()
    return response


@router.patch("/scenarios/{scenario_id}")
def patch_scenario(
    scenario_id: uuid.UUID,
    body: PatchScenarioRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.scenario.edit", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_scenario(session, principal, scenario_id)
    _scenario_draft(item)
    _check_version(item.row_version, body.row_version)
    for field in ("name", "description", "disclaimer"):
        value = getattr(body, field)
        if value is not None:
            setattr(item, field, value)
    if body.parameters is not None:
        parameters = validate_scenario_parameters(body.parameters)
        item.parameters_json = parameters
        item.checksum = scenario_checksum(parameters)
        _sync_scenario_parameters(session, item)
    item.row_version += 1
    session.flush()
    response = scenario_payload(item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


def _scenario_workflow_endpoint(
    scenario_id: uuid.UUID,
    body: WorkflowRequest,
    request: Request,
    key: str,
    principal: Principal,
    session: Session,
    action: str,
) -> dict[str, Any]:
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    item = _require_scenario(session, principal, scenario_id)
    _check_version(item.row_version, body.row_version)
    if action == "submit":
        assert_permission(principal, "investment.scenario.edit", "investment-prioritisation")
        _scenario_draft(item)
        validate_scenario_parameters(item.parameters_json)
        item.state = "UNDER_REVIEW"
        item.submitted_by = principal.user_id
        item.submitted_at = now()
    elif action == "approve":
        assert_permission(principal, "investment.scenario.approve", "investment-prioritisation")
        if item.state != "UNDER_REVIEW":
            raise conflict("SCENARIO_NOT_APPROVABLE", "The scenario is not under review.")
        if item.created_by == principal.user_id:
            raise conflict("SEPARATION_OF_DUTIES", "A scenario creator cannot approve it.")
        item.state = "APPROVED"
        item.approved_by = principal.user_id
        item.approved_at = now()
    else:
        assert_permission(principal, "investment.scenario.approve", "investment-prioritisation")
        if item.state != "APPROVED":
            raise conflict("SCENARIO_NOT_RETIRABLE", "Only an approved scenario can be retired.")
        item.state = "RETIRED"
        item.retired_at = now()
    record_event(
        session, action=f"investment.scenario.{action}", resource_type="scenario",
        resource_id=item.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        reason=body.reason, after={"state": item.state},
    )
    session.flush()
    session.refresh(item)
    response = scenario_payload(item)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


@router.post("/scenarios/{scenario_id}/submit")
def submit_scenario(
    scenario_id: uuid.UUID, body: WorkflowRequest, request: Request,
    key: str = Depends(require_idempotency_key), principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _scenario_workflow_endpoint(scenario_id, body, request, key, principal, session, "submit")


@router.post("/scenarios/{scenario_id}/approve")
def approve_scenario(
    scenario_id: uuid.UUID, body: WorkflowRequest, request: Request,
    key: str = Depends(require_idempotency_key), principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _scenario_workflow_endpoint(scenario_id, body, request, key, principal, session, "approve")


@router.post("/scenarios/{scenario_id}/retire")
def retire_scenario(
    scenario_id: uuid.UUID, body: WorkflowRequest, request: Request,
    key: str = Depends(require_idempotency_key), principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _scenario_workflow_endpoint(scenario_id, body, request, key, principal, session, "retire")


@router.get("/runs")
def list_runs(
    status: str | None = None,
    scenario_id: uuid.UUID | None = None,
    requested_by: uuid.UUID | None = None,
    migration_source: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.view", "investment-prioritisation")
    query = select(InvestmentAnalysisRun).where(
        InvestmentAnalysisRun.workspace_id == principal.active_workspace_id
    )
    if status:
        query = query.where(InvestmentAnalysisRun.status == status.lower())
    if scenario_id:
        query = query.where(InvestmentAnalysisRun.scenario_id == scenario_id)
    if requested_by:
        query = query.where(InvestmentAnalysisRun.requested_by == requested_by)
    if migration_source:
        query = query.where(InvestmentAnalysisRun.migration_source == migration_source)
    rows, meta = _page(
        query.order_by(InvestmentAnalysisRun.requested_at.desc()), session, page, page_size
    )
    visible = [item for item in rows if can_access_run(session, principal, item)]
    return {"items": [run_payload(session, item) for item in visible], "meta": meta}


@router.post("/runs", status_code=202)
def create_run(
    body: CreateRunRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.create", "investment-prioritisation")
    request_document = body.model_dump(mode="json")
    request_hash = checksum_json(request_document)
    existing = session.scalar(
        select(InvestmentAnalysisRun).where(
            InvestmentAnalysisRun.workspace_id == principal.active_workspace_id,
            InvestmentAnalysisRun.requested_by == principal.user_id,
            InvestmentAnalysisRun.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise conflict(
                "IDEMPOTENCY_KEY_CONFLICT",
                "The idempotency key was already used with a different canonical run request.",
            )
        return run_payload(session, existing, detail=True)

    input_set = _require_input(session, principal, body.input_set_id)
    if input_set.status != "LOCKED" or not input_set.checksum:
        raise conflict("LOCKED_INPUT_SET_REQUIRED", "Analysis requires a locked input set.")
    if body.run_mode not in input_set.run_mode_compatibility:
        raise conflict("RUN_MODE_NOT_SUPPORTED", "The input set does not support this run mode.")
    readiness = validate_input_set(
        session, input_set, principal, require_published=body.run_mode == "FORMAL"
    )
    if not readiness["ready"]:
        raise conflict("INPUT_SET_NOT_READY", "The exact input versions are no longer ready.", errors=readiness["errors"])
    method = _require_method_version(session, body.method_version_id)
    scenario = _require_scenario(session, principal, body.scenario_id)
    if method.state != "APPROVED" or scenario.state != "APPROVED":
        raise conflict("APPROVED_GOVERNANCE_REQUIRED", "The method and scenario must both be approved.")
    if scenario.method_version_id != method.id:
        raise conflict("SCENARIO_METHOD_MISMATCH", "The scenario is bound to a different method version.")
    allowed = set(method.specification_json.get("allowed_overrides", []))
    if not set(body.overrides) <= allowed:
        raise conflict("OVERRIDE_NOT_ALLOWED", "The selected method does not allow an override.")
    base = validate_scenario_parameters(scenario.parameters_json)
    entered_weights = dict(base["weights"])
    if "weights" in body.overrides:
        entered_weights.update(
            {code: float(value) for code, value in body.overrides["weights"].items()}
        )
    normalised = normalise_weights(entered_weights, list(INDICATOR_CODES))
    minimum = float(body.overrides.get("min_rice_area_ha", base["min_rice_area_ha"]))
    parameters = {
        "weights": normalised,
        "entered_weights": entered_weights,
        "min_rice_area_ha": minimum,
        "overrides": body.overrides,
        "scenario_parameters_checksum": scenario.checksum,
    }
    run_id = uuid.uuid4()
    job_id = uuid.uuid4()
    metadata = execution_metadata()
    run = InvestmentAnalysisRun(
        id=run_id,
        workspace_id=principal.active_workspace_id,
        input_set_id=input_set.id,
        method_version_id=method.id,
        scenario_id=scenario.id,
        run_mode=body.run_mode,
        parameters_snapshot=parameters,
        input_set_checksum=input_set.checksum,
        method_checksum=method.checksum,
        scenario_checksum=scenario.checksum,
        requested_by=principal.user_id,
        processing_job_id=job_id,
        idempotency_key=key,
        request_hash=request_hash,
        status="queued",
        progress=0,
        current_step="queued",
        code_ref=metadata["code_ref"],
        worker_task_version=WORKER_TASK_VERSION,
        container_metadata={key: value for key, value in metadata.items() if key != "code_ref"},
        warnings_json=list(readiness["warnings"]),
        exclusions_json=[],
        failure_json={},
        correlation_id=request.state.correlation_id,
    )
    job = ProcessingJob(
        id=job_id,
        workspace_id=principal.active_workspace_id,
        job_type=WORKER_TASK_VERSION,
        module_key="investment-prioritisation",
        resource_type="analysis_run",
        resource_id=run.id,
        status="QUEUED",
        progress=0,
        idempotency_key=f"investment-run:{checksum_json({'workspace': str(principal.active_workspace_id), 'actor': str(principal.user_id), 'key': key})}",
        payload_json={"run_id": str(run.id)},
        result_json={},
        max_attempts=2,
        requested_by=principal.user_id,
    )
    session.add_all([run, job])
    session.flush()
    create_run_inputs(session, run, input_set)
    steps = [
        ("validate-inputs", "Validate exact inputs"),
        ("prepare", "Prepare analysis records"),
        ("score", "Calculate deterministic scores"),
        ("materialise-results", "Materialise native results"),
        ("register-output", "Register catalog output"),
        ("finalise", "Finalise checksums and status"),
    ]
    for ordinal, (step_key, label) in enumerate(steps):
        session.add(
            JobStep(
                id=stable_output_id("job-step", f"{job.id}:{step_key}"),
                job_id=job.id,
                ordinal=ordinal,
                step_key=step_key,
                label=label,
                status="PENDING",
            )
        )
    record_event(
        session, action="investment.analysis.create", resource_type="analysis_run",
        resource_id=run.id, outcome="success", correlation_id=run.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        after={
            "job_id": str(job.id), "input_set_checksum": run.input_set_checksum,
            "method_checksum": run.method_checksum, "scenario_checksum": run.scenario_checksum,
        },
    )
    session.commit()
    dispatch = "queued"
    try:
        run_prioritisation.delay(str(run.id), str(job.id))
    except Exception:
        dispatch = "durable_queue_pending"
    response = run_payload(session, run, detail=True)
    response["dispatch"] = dispatch
    return response


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.view", "investment-prioritisation")
    return run_payload(session, require_run_access(session, principal, run_id), detail=True)


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: uuid.UUID,
    body: CancelRunRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.cancel", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    run = require_run_access(session, principal, run_id)
    if run.requested_by != principal.user_id and "workspace_admin" not in principal.role_keys:
        raise forbidden("RUN_CANCEL_DENIED", "Only the run owner or a workspace administrator can cancel it.")
    if run.current_step in {"register-output", "finalise"}:
        raise conflict("RUN_CANCELLATION_TOO_LATE", "Output registration has started and cannot be interrupted safely.")
    if run.status not in {"queued", "running", "cancel_requested"}:
        raise conflict("RUN_NOT_CANCELLABLE", "The run is not cancellable.", status=run.status)
    run.status = "cancel_requested"
    record_event(
        session, action="investment.analysis.cancel", resource_type="analysis_run",
        resource_id=run.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        reason=body.reason, after={"status": run.status},
    )
    session.flush()
    response = run_payload(session, run)
    _remember_mutation(session, principal, key, request, request_hash, response)
    session.commit()
    return response


@router.get("/runs/{run_id}/results")
def get_run_results(
    run_id: uuid.UUID,
    eligible: bool | None = None,
    priority_band: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=500),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.view", "investment-prioritisation")
    run = require_run_access(session, principal, run_id)
    records = result_records(session, run.id)
    if eligible is not None:
        records = [item for item in records if item["eligible"] is eligible]
    if priority_band:
        records = [item for item in records if item["priority_band"] == priority_band]
    total = len(records)
    items = records[(page - 1) * page_size : page * page_size]
    return {
        "run_id": str(run.id), "status": run.status, "items": items,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature", "id": item["id"], "geometry": item["geometry"],
                    "properties": {key: value for key, value in item.items() if key != "geometry"},
                }
                for item in items
            ],
        },
        "meta": {"page": page, "page_size": page_size, "total": total},
        "result_checksum": run.result_checksum,
        "disclaimer": DEMO_DISCLAIMER,
    }


@router.get("/runs/{run_id}/areas/{area_code}")
def get_run_area(
    run_id: uuid.UUID,
    area_code: str,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.view", "investment-prioritisation")
    run = require_run_access(session, principal, run_id)
    item = next((row for row in result_records(session, run.id) if row["code"] == area_code), None)
    if item is None:
        raise not_found("Run area")
    return item


@router.get("/runs/{run_id}/lineage")
def get_run_lineage(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.view", "investment-prioritisation")
    return lineage_payload(session, require_run_access(session, principal, run_id))


@router.get("/runs/{run_id}/audit")
def get_run_audit(
    run_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.view", "investment-prioritisation")
    return audit_payload(session, require_run_access(session, principal, run_id))


@router.post("/runs/{run_id}/submit-result-review", status_code=201)
def submit_result_review(
    run_id: uuid.UUID,
    body: WorkflowRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.result.submit_review", "investment-prioritisation")
    cached, request_hash = _cached_mutation(session, principal, key, request, body.model_dump(mode="json"))
    if cached is not None:
        return cached
    run = require_run_access(session, principal, run_id)
    if run.status not in {"succeeded", "succeeded_with_warnings"} or not run.output_dataset_version_id:
        raise conflict("RESULT_NOT_REVIEWABLE", "A successful registered output is required.")
    version = session.get(CatalogDatasetVersion, run.output_dataset_version_id)
    if version is None or version.state != "VALIDATED":
        raise conflict("RESULT_NOT_REVIEWABLE", "The result is not in the validated state.", state=version.state if version else None)
    _check_version(version.row_version, body.row_version)
    group = session.scalar(
        select(Group).where(
            Group.workspace_id == principal.active_workspace_id,
            Group.slug == "data-review-board",
        )
    )
    review = ReviewRequest(
        id=stable_output_id("output-review", str(run.id)),
        dataset_version_id=version.id,
        review_type="publication",
        requested_by=principal.user_id,
        reviewer_group_id=group.id if group else None,
        status="OPEN",
        policy_snapshot={
            "creator_cannot_be_sole_reviewer": True,
            "reviewer_does_not_imply_publisher": True,
            "synthetic_output": True,
        },
    )
    session.add(review)
    version.state = "IN_REVIEW"
    version.submitted_at = now()
    record_event(
        session, action="investment.result.submit", resource_type="analysis_run",
        resource_id=run.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        reason=body.reason, after={"review_id": str(review.id), "dataset_version_id": str(version.id)},
    )
    response = {
        "id": str(review.id), "run_id": str(run.id),
        "dataset_version_id": str(version.id), "status": review.status,
    }
    _remember_mutation(session, principal, key, request, request_hash, response, status=201)
    session.commit()
    return response


@router.get("/runs/{run_id}/assets")
def get_run_assets(
    run_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.export", "investment-prioritisation")
    run = require_run_access(session, principal, run_id)
    items = asset_payloads(session, run, sign=True)
    record_event(
        session, action="investment.analysis.export", resource_type="analysis_run",
        resource_id=run.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        after={"asset_ids": [item["id"] for item in items], "signed": True},
    )
    session.commit()
    return {"items": items, "meta": {"total": len(items), "short_lived_urls": True}}


@router.post("/runs/{run_id}/exports", status_code=201)
def create_export(
    run_id: uuid.UUID,
    body: CreateExportRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.export", "investment-prioritisation")
    run = require_run_access(session, principal, run_id)
    if not run.output_dataset_version_id:
        raise conflict("RUN_OUTPUT_UNAVAILABLE", "The run has no registered output assets.")
    asset = session.get(CatalogAsset, body.asset_id)
    if asset is None or asset.dataset_version_id != run.output_dataset_version_id:
        raise not_found("Run asset")
    job_key = f"investment-export:{checksum_json({'workspace': str(principal.active_workspace_id), 'actor': str(principal.user_id), 'key': key})}"
    existing = session.scalar(select(ProcessingJob).where(ProcessingJob.idempotency_key == job_key))
    if existing:
        if existing.resource_id != run.id or existing.payload_json.get("asset_id") != str(asset.id):
            raise conflict("IDEMPOTENCY_KEY_CONFLICT", "The export key was used for another asset.")
        return {"id": str(existing.id), "run_id": str(run.id), "asset_id": str(asset.id), "status": existing.status}
    job = ProcessingJob(
        workspace_id=principal.active_workspace_id,
        job_type="investment:export-run:v1",
        module_key="investment-prioritisation",
        resource_type="analysis_run",
        resource_id=run.id,
        status="SUCCEEDED",
        progress=100,
        idempotency_key=job_key,
        payload_json={"asset_id": str(asset.id)},
        result_json={"asset_id": str(asset.id)},
        attempt=1,
        max_attempts=1,
        requested_by=principal.user_id,
        started_at=now(),
        completed_at=now(),
    )
    session.add(job)
    session.flush()
    record_event(
        session, action="investment.analysis.export", resource_type="analysis_run",
        resource_id=run.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        after={"export_id": str(job.id), "asset_id": str(asset.id)},
    )
    session.commit()
    return {"id": str(job.id), "run_id": str(run.id), "asset_id": str(asset.id), "status": job.status}


@router.get("/exports/{export_id}")
def get_export(
    export_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.export", "investment-prioritisation")
    job = session.get(ProcessingJob, export_id)
    if (
        job is None
        or job.workspace_id != principal.active_workspace_id
        or job.job_type != "investment:export-run:v1"
    ):
        raise not_found("Export")
    run = require_run_access(session, principal, job.resource_id)
    asset_id = uuid.UUID(job.result_json["asset_id"])
    item = next((asset for asset in asset_payloads(session, run, sign=True) if asset["id"] == str(asset_id)), None)
    if item is None:
        raise not_found("Export asset")
    record_event(
        session, action="investment.analysis.export.download", resource_type="analysis_run",
        resource_id=run.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        after={"export_id": str(job.id), "asset_id": str(asset_id)},
    )
    session.commit()
    return {"id": str(job.id), "status": job.status, "asset": item}


@router.get("/comparisons")
def list_comparisons(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.compare", "investment-prioritisation")
    rows, meta = _page(
        select(InvestmentRunComparison)
        .where(InvestmentRunComparison.workspace_id == principal.active_workspace_id)
        .order_by(InvestmentRunComparison.created_at.desc()),
        session,
        page,
        page_size,
    )
    visible = [
        item
        for item in rows
        if can_access_run(session, principal, session.get(InvestmentAnalysisRun, item.left_run_id))
        and can_access_run(session, principal, session.get(InvestmentAnalysisRun, item.right_run_id))
    ]
    return {"items": [comparison_payload(item, detail=False) for item in visible], "meta": meta}


@router.post("/comparisons", status_code=201)
def create_run_comparison(
    body: CreateComparisonRequest,
    request: Request,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.compare", "investment-prioritisation")
    request_hash = checksum_json(body.model_dump(mode="json"))
    existing = session.scalar(
        select(InvestmentRunComparison).where(
            InvestmentRunComparison.workspace_id == principal.active_workspace_id,
            InvestmentRunComparison.created_by == principal.user_id,
            InvestmentRunComparison.idempotency_key == key,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise conflict("IDEMPOTENCY_KEY_CONFLICT", "The comparison key was used with another payload.")
        return comparison_payload(existing)
    left = require_run_access(session, principal, body.left_run_id)
    right = require_run_access(session, principal, body.right_run_id)
    item = create_comparison(
        session, left, right, actor_id=principal.user_id, idempotency_key=key,
        request_hash=request_hash, top_n=body.top_n,
    )
    record_event(
        session, action="investment.analysis.compare", resource_type="run_comparison",
        resource_id=item.id, outcome="success", correlation_id=request.state.correlation_id,
        actor_id=principal.user_id, workspace_id=principal.active_workspace_id,
        after={"left_run_id": str(left.id), "right_run_id": str(right.id), "checksum": item.checksum},
    )
    session.commit()
    return comparison_payload(item)


@router.get("/comparisons/{comparison_id}")
def get_comparison(
    comparison_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.compare", "investment-prioritisation")
    item = session.get(InvestmentRunComparison, comparison_id)
    if item is None or item.workspace_id != principal.active_workspace_id:
        raise not_found("Comparison")
    require_run_access(session, principal, item.left_run_id)
    require_run_access(session, principal, item.right_run_id)
    return comparison_payload(item)


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def investment_metrics(principal: Principal = Depends(get_current_principal)) -> str:
    assert_permission(principal, "system.health.view")
    return prometheus_text()
