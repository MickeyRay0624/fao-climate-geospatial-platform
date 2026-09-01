from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit_service import record_event
from app.authorization import assert_permission
from app.config import (
    ALLOW_INSECURE_DEV_FILE_SCAN,
    APP_ENV,
    AUTH_MODE,
    REDIS_URL,
)
from app.database import get_session
from app.errors import conflict, not_found
from app.identity import Principal, get_current_principal
from app.jobs import celery_app, process_upload_session
from app.platform_models import (
    AuditEvent,
    CatalogDatasetVersion,
    Group,
    GroupMembership,
    JobStep,
    InvestmentAnalysisRun,
    Module,
    ProcessingJob,
    Role,
    RoleAssignment,
    User,
    WorkspaceMembership,
    WorkspaceModule,
)


core_router = APIRouter(tags=["Core"])
jobs_router = APIRouter(prefix="/api/jobs/v1", tags=["Jobs"])
audit_router = APIRouter(prefix="/api/audit/v1", tags=["Audit"])
governance_router = APIRouter(prefix="/api/governance/v1", tags=["Governance"])


def _user(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "external_subject": user.external_subject,
        "display_name": user.display_name,
        "email": user.email,
        "status": user.status,
        "locale": user.locale,
    }


def _principal_payload(principal: Principal) -> dict[str, Any]:
    return {
        "id": str(principal.user_id),
        "external_subject": principal.external_subject,
        "issuer": principal.issuer,
        "display_name": principal.display_name,
        "email": principal.email,
        "active_workspace": {"id": str(principal.active_workspace_id), "name": principal.workspace_name},
        "workspace_memberships": principal.workspace_memberships,
        "group_ids": [str(item) for item in sorted(principal.group_ids, key=str)],
        "roles": sorted(principal.role_keys),
        "effective_permissions": sorted(principal.effective_permissions),
        "enabled_modules": sorted(principal.enabled_modules),
        "dev_auth": principal.dev_auth,
    }


@core_router.get("/api/me")
def me(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    record_event(
        session,
        action="identity.context.resolve",
        resource_type="user",
        resource_id=principal.user_id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        after={"auth_mode": "development" if principal.dev_auth else "oidc"},
    )
    session.commit()
    return _principal_payload(principal)


def _navigation(principal: Principal, session: Session) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = [
        {"path": "/home", "title": "Overview", "section": "Workspace", "permission": "workspace.view", "icon": "home"},
        {"path": "/data/catalog", "title": "Team catalogue", "section": "Data Hub", "permission": "data.catalog.enter", "icon": "database"},
        {"path": "/data/mine", "title": "My data", "section": "Data Hub", "permission": "data.catalog.enter", "icon": "folder"},
        {"path": "/data/collections", "title": "Collections", "section": "Data Hub", "permission": "data.catalog.enter", "icon": "collection"},
        {"path": "/data/uploads", "title": "Upload centre", "section": "Data Hub", "permission": "dataset.upload_version", "icon": "upload"},
        {"path": "/data/reviews", "title": "Reviews", "section": "Data Hub", "permission": "dataset.review", "icon": "check"},
        {"path": "/apps/investment-prioritisation/overview", "title": "Investment prioritisation", "section": "Applications", "permission": "apps.investment.use", "module": "investment-prioritisation", "icon": "map"},
        {"path": "/governance/members", "title": "Members", "section": "Governance", "permission": "workspace.manage_members", "icon": "users"},
        {"path": "/governance/groups", "title": "Groups", "section": "Governance", "permission": "workspace.manage_groups", "icon": "groups"},
        {"path": "/governance/roles", "title": "Roles", "section": "Governance", "permission": "workspace.manage_roles", "icon": "shield"},
        {"path": "/governance/audit", "title": "Audit log", "section": "Governance", "permission": "audit.view", "icon": "audit"},
        {"path": "/help", "title": "Help & boundaries", "section": "Support", "permission": "workspace.view", "icon": "help"},
    ]
    return [
        route for route in routes
        if route["permission"] in principal.effective_permissions
        and (not route.get("module") or route["module"] in principal.enabled_modules)
    ]


@core_router.get("/api/me/capabilities")
def capabilities(
    workspace_id: UUID | None = None,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if workspace_id and workspace_id != principal.active_workspace_id:
        raise not_found("Workspace")
    return {
        "current_user": _principal_payload(principal),
        "active_workspace": {"id": str(principal.active_workspace_id), "name": principal.workspace_name},
        "effective_permissions": sorted(principal.effective_permissions),
        "enabled_modules": sorted(principal.enabled_modules),
        "navigation": _navigation(principal, session),
        "feature_flags": {
            "data_hub.direct_upload": True,
            "data_hub.background_validation": True,
            "development_scan_bypass": APP_ENV in {"development", "test"} and ALLOW_INSECURE_DEV_FILE_SCAN,
            "extension_field_support": False,
        },
        "development_identity": principal.dev_auth,
        "auth_mode": AUTH_MODE,
    }


@core_router.get("/api/modules")
def modules(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "workspace.view")
    rows = session.execute(
        select(Module, WorkspaceModule)
        .join(WorkspaceModule, WorkspaceModule.module_id == Module.id)
        .where(WorkspaceModule.workspace_id == principal.active_workspace_id)
        .order_by(Module.name)
    ).all()
    return {
        "items": [
            {
                "id": str(module.id),
                "module_key": module.module_key,
                "name": module.name,
                "description": module.description,
                "module_version": module.module_version,
                "contract_version": module.contract_version,
                "status": module.status,
                "enabled": workspace_module.enabled,
                "manifest_valid": module.manifest_valid,
                "routes": module.manifest.get("routes", []),
                "feature_flags": workspace_module.feature_flags,
            }
            for module, workspace_module in rows
        ]
    }


@core_router.get("/api/dev/personas")
def dev_personas(session: Session = Depends(get_session)) -> dict[str, Any]:
    if APP_ENV not in {"development", "test"} or AUTH_MODE != "dev":
        raise not_found("Development personas")
    users = session.scalars(
        select(User).where(User.issuer == "urn:fao:climate-platform:dev", User.status == "active").order_by(User.display_name)
    ).all()
    return {"items": [_user(user) for user in users], "development_only": True}


class ModuleStateRequest(BaseModel):
    enabled: bool
    reason: str


@core_router.patch("/api/modules/{module_key}")
def update_module(
    module_key: str,
    body: ModuleStateRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "workspace.enable_modules")
    row = session.execute(
        select(Module, WorkspaceModule)
        .join(WorkspaceModule, WorkspaceModule.module_id == Module.id)
        .where(Module.module_key == module_key, WorkspaceModule.workspace_id == principal.active_workspace_id)
    ).first()
    if row is None:
        raise not_found("Module")
    module, workspace_module = row
    if not module.manifest_valid and body.enabled:
        raise conflict("MODULE_MANIFEST_INVALID", "A module with an invalid contract cannot be enabled.")
    before = workspace_module.enabled
    workspace_module.enabled = body.enabled
    record_event(
        session,
        action="core.module.enable" if body.enabled else "core.module.disable",
        resource_type="module",
        resource_id=module.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        reason=body.reason,
        before={"enabled": before},
        after={"enabled": body.enabled},
    )
    session.commit()
    return {"module_key": module.module_key, "enabled": workspace_module.enabled}


def job_payload(session: Session, job: ProcessingJob) -> dict[str, Any]:
    steps = session.scalars(select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.ordinal)).all()
    return {
        "id": str(job.id),
        "job_type": job.job_type,
        "module_key": job.module_key,
        "resource_type": job.resource_type,
        "resource_id": str(job.resource_id),
        "status": job.status,
        "progress": job.progress,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "result": job.result_json,
        "error": {"code": job.error_code, "message": job.error_message} if job.error_code else None,
        "requested_by": str(job.requested_by),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "steps": [
            {"key": step.step_key, "label": step.label, "status": step.status, "details": step.details_json}
            for step in steps
        ],
    }


@jobs_router.get("/jobs")
def list_jobs(
    status: str | None = None,
    mine: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    permission = "jobs.view_own" if mine or "jobs.view_workspace" not in principal.effective_permissions else "jobs.view_workspace"
    assert_permission(principal, permission)
    query = select(ProcessingJob).where(ProcessingJob.workspace_id == principal.active_workspace_id)
    if permission == "jobs.view_own":
        query = query.where(ProcessingJob.requested_by == principal.user_id)
    if status:
        query = query.where(ProcessingJob.status == status.upper())
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(ProcessingJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [job_payload(session, job) for job in rows], "meta": {"page": page, "page_size": page_size, "total": total}}


@jobs_router.get("/jobs/{job_id}")
def get_job(job_id: UUID, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    job = session.get(ProcessingJob, job_id)
    if job is None or job.workspace_id != principal.active_workspace_id:
        raise not_found("Job")
    if job.requested_by != principal.user_id:
        assert_permission(principal, "jobs.view_workspace")
    else:
        assert_permission(principal, "jobs.view_own")
    return job_payload(session, job)


class RetryRequest(BaseModel):
    reason: str


@jobs_router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: UUID,
    body: RetryRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "jobs.retry")
    job = session.get(ProcessingJob, job_id)
    if job is None or job.workspace_id != principal.active_workspace_id:
        raise not_found("Job")
    if job.status != "FAILED" or job.attempt >= job.max_attempts:
        raise conflict("JOB_NOT_RETRYABLE", "The job is not eligible for retry.", status=job.status, attempt=job.attempt)
    upload_id = job.payload_json.get("upload_session_id")
    run_id = job.payload_json.get("run_id")
    if job.job_type == "investment:run-prioritisation:v1":
        run = session.get(InvestmentAnalysisRun, job.resource_id)
        if run is None or not run_id or str(run.id) != str(run_id):
            raise conflict("JOB_NOT_RETRYABLE", "The original analysis run is unavailable.")
        run.status = "queued"
        run.progress = 0
        run.current_step = "queued"
        run.failure_json = {}
        run.completed_at = None
    else:
        if not upload_id:
            raise conflict("JOB_NOT_RETRYABLE", "The original upload session is unavailable.")
        version = session.get(CatalogDatasetVersion, job.resource_id)
        if version:
            version.state = "PROCESSING"
    job.status = "QUEUED"
    job.progress = 0
    job.error_code = None
    job.error_message = None
    job.completed_at = None
    for step in session.scalars(select(JobStep).where(JobStep.job_id == job.id)).all():
        step.status = "PENDING"
        step.started_at = None
        step.completed_at = None
        step.details_json = {}
    record_event(
        session,
        action="jobs.processing.retry",
        resource_type="processing_job",
        resource_id=job.id,
        outcome="success",
        correlation_id=request.state.correlation_id,
        actor_id=principal.user_id,
        workspace_id=principal.active_workspace_id,
        reason=body.reason,
        after={"attempt": job.attempt + 1},
    )
    session.commit()
    if job.job_type == "investment:run-prioritisation:v1":
        from app.investment.tasks import run_prioritisation

        run_prioritisation.delay(str(job.resource_id), str(job.id))
    else:
        process_upload_session.delay(upload_id, str(job.id), request.state.correlation_id)
    return job_payload(session, job)


@audit_router.get("/events")
def list_audit_events(
    action: str | None = None,
    outcome: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "audit.view")
    query = select(AuditEvent).where(AuditEvent.workspace_id == principal.active_workspace_id)
    if action:
        query = query.where(AuditEvent.action == action)
    if outcome:
        query = query.where(AuditEvent.outcome == outcome)
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditEvent.resource_id == resource_id)
    if correlation_id:
        query = query.where(AuditEvent.correlation_id == correlation_id)
    if search:
        term = f"%{search}%"
        query = query.where(or_(AuditEvent.action.ilike(term), AuditEvent.resource_id.ilike(term), AuditEvent.reason.ilike(term)))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(AuditEvent.event_time.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [
            {
                "id": str(event.id), "event_time": event.event_time.isoformat(),
                "actor_id": str(event.actor_id) if event.actor_id else None,
                "action": event.action, "resource_type": event.resource_type,
                "resource_id": event.resource_id, "outcome": event.outcome,
                "reason": event.reason, "correlation_id": event.correlation_id,
                "before": event.before_json, "after": event.after_json,
                "severity": event.severity,
            }
            for event in rows
        ],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


@governance_router.get("/members")
def list_members(principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    assert_permission(principal, "workspace.manage_members")
    rows = session.execute(
        select(User, WorkspaceMembership)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(WorkspaceMembership.workspace_id == principal.active_workspace_id)
        .order_by(User.display_name)
    ).all()
    return {
        "items": [
            {**_user(user), "membership_status": membership.status, "joined_at": membership.joined_at.isoformat(), "expires_at": membership.expires_at.isoformat() if membership.expires_at else None}
            for user, membership in rows
        ]
    }


@governance_router.get("/groups")
def list_groups(principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    assert_permission(principal, "workspace.manage_groups")
    groups = session.scalars(select(Group).where(Group.workspace_id == principal.active_workspace_id).order_by(Group.name)).all()
    return {
        "items": [
            {
                "id": str(group.id), "slug": group.slug, "name": group.name, "description": group.description,
                "members": [
                    _user(user)
                    for user in session.scalars(
                        select(User)
                        .join(GroupMembership, GroupMembership.user_id == User.id)
                        .where(GroupMembership.group_id == group.id)
                        .order_by(User.display_name)
                    ).all()
                ],
            }
            for group in groups
        ]
    }


@governance_router.get("/roles")
def list_roles(principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    assert_permission(principal, "workspace.manage_roles")
    roles = session.scalars(select(Role).where(Role.workspace_id == principal.active_workspace_id).order_by(Role.name)).all()
    items = []
    for role in roles:
        assignments = session.execute(
            select(RoleAssignment, User)
            .join(User, User.id == RoleAssignment.subject_id)
            .where(RoleAssignment.role_id == role.id, RoleAssignment.subject_type == "user", RoleAssignment.scope_id == principal.active_workspace_id)
        ).all()
        items.append(
            {
                "id": str(role.id), "role_key": role.role_key, "name": role.name,
                "description": role.description,
                "assignments": [
                    {"id": str(assignment.id), "subject": _user(user), "valid_until": assignment.valid_until.isoformat() if assignment.valid_until else None, "reason": assignment.reason}
                    for assignment, user in assignments
                ],
            }
        )
    return {"items": items}


def dependency_health() -> dict[str, Any]:
    broker = "unavailable"
    worker = "unavailable"
    try:
        Redis.from_url(REDIS_URL, socket_timeout=0.5).ping()
        broker = "ok"
        ping = celery_app.control.inspect(timeout=0.5).ping() or {}
        worker = "ok" if ping else "unavailable"
    except Exception:
        pass
    return {"redis": broker, "worker": worker}
