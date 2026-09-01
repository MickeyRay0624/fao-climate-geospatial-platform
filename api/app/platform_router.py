from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit_service import record_event
from app.authorization import assert_permission, can_access_dataset
from app.config import (
    ALLOW_INSECURE_DEV_FILE_SCAN,
    APP_ENV,
    AUTH_MODE,
    REDIS_URL,
)
from app.database import get_session
from app.errors import conflict, not_found
from app.identity import Principal, get_current_principal
from app.extension_models import ExtensionCase, FollowUp, KnowledgeItem
from app.jobs import celery_app, process_upload_session
from app.platform_models import (
    AuditEvent,
    CatalogDataset,
    CatalogDatasetVersion,
    Collection,
    Group,
    GroupMembership,
    JobStep,
    InvestmentAnalysisRun,
    InvestmentAnalysisInputSet,
    Module,
    ProcessingJob,
    QualityIssue,
    QualityRun,
    ReviewRequest,
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
        {"path": "/apps", "title": "All applications", "section": "Applications", "permission": "workspace.view", "icon": "apps"},
        {"path": "/apps/investment-prioritisation/overview", "title": "Investment prioritisation", "section": "Applications", "permission": "apps.investment.use", "module": "investment-prioritisation", "icon": "map"},
        {"path": "/apps/extension-field-support/worklist", "title": "Extension field support", "section": "Applications", "permission": "apps.extension.use", "module": "extension-field-support", "icon": "field"},
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
            "extension_field_support": "extension-field-support" in principal.enabled_modules,
        },
        "development_identity": principal.dev_auth,
        "auth_mode": AUTH_MODE,
    }


@core_router.get("/api/home")
def home_dashboard(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "workspace.view")
    catalogue_rows = session.scalars(
        select(CatalogDataset)
        .where(
            CatalogDataset.workspace_id == principal.active_workspace_id,
            CatalogDataset.lifecycle_status != "ARCHIVED",
        )
        .order_by(CatalogDataset.updated_at.desc())
    ).all()
    visible_datasets = [
        item
        for item in catalogue_rows
        if can_access_dataset(session, principal, item, "dataset.view_metadata")
    ]
    recent_datasets = [
        {
            "id": str(item.id),
            "title": item.title,
            "data_kind": item.data_kind,
            "published": item.current_published_version_id is not None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in visible_datasets[:5]
    ]
    jobs_query = select(ProcessingJob).where(
        ProcessingJob.workspace_id == principal.active_workspace_id
    )
    if "jobs.view_workspace" not in principal.effective_permissions:
        jobs_query = jobs_query.where(ProcessingJob.requested_by == principal.user_id)
    jobs = session.scalars(jobs_query).all()
    role_cards: dict[str, Any] = {}
    if "dataset.create" in principal.effective_permissions:
        role_cards["contributor"] = {
            "draft_versions": session.scalar(
                select(func.count(CatalogDatasetVersion.id)).where(
                    CatalogDatasetVersion.created_by == principal.user_id,
                    CatalogDatasetVersion.state.in_(
                        ["DRAFT", "UPLOADING", "PROCESSING", "VALIDATION_FAILED"]
                    ),
                )
            )
            or 0,
            "failed_or_warning_jobs": sum(
                item.status == "FAILED"
                or bool((item.result_json or {}).get("warnings"))
                for item in jobs
            ),
            "pending_submissions": session.scalar(
                select(func.count(CatalogDatasetVersion.id)).where(
                    CatalogDatasetVersion.created_by == principal.user_id,
                    CatalogDatasetVersion.state.in_(["VALIDATED", "CHANGES_REQUESTED"]),
                )
            )
            or 0,
        }
    if {"dataset.review", "dataset.publish"} & principal.effective_permissions:
        blocking_query = (
            select(func.count(QualityIssue.id))
            .join(QualityRun, QualityRun.id == QualityIssue.quality_run_id)
            .join(
                CatalogDatasetVersion,
                CatalogDatasetVersion.id == QualityRun.dataset_version_id,
            )
            .join(CatalogDataset, CatalogDataset.id == CatalogDatasetVersion.dataset_id)
            .where(
                CatalogDataset.workspace_id == principal.active_workspace_id,
                QualityIssue.severity == "BLOCKING",
                QualityIssue.resolution_status == "OPEN",
            )
        )
        role_cards["reviewer"] = {
            "assigned_reviews": session.scalar(
                select(func.count(ReviewRequest.id))
                .join(
                    CatalogDatasetVersion,
                    CatalogDatasetVersion.id == ReviewRequest.dataset_version_id,
                )
                .join(CatalogDataset, CatalogDataset.id == CatalogDatasetVersion.dataset_id)
                .where(
                    CatalogDataset.workspace_id == principal.active_workspace_id,
                    ReviewRequest.status.in_(["OPEN", "IN_PROGRESS"]),
                )
            )
            or 0,
            "pending_publication": session.scalar(
                select(func.count(CatalogDatasetVersion.id))
                .join(CatalogDataset, CatalogDataset.id == CatalogDatasetVersion.dataset_id)
                .where(
                    CatalogDataset.workspace_id == principal.active_workspace_id,
                    CatalogDatasetVersion.state == "APPROVED",
                )
            )
            or 0,
            "blocking_quality_issues": session.scalar(blocking_query) or 0,
        }
    if "apps.investment.use" in principal.effective_permissions:
        run_query = select(InvestmentAnalysisRun).where(
            InvestmentAnalysisRun.workspace_id == principal.active_workspace_id
        )
        if "investment.run.view" not in principal.effective_permissions:
            run_query = run_query.where(
                InvestmentAnalysisRun.requested_by == principal.user_id
            )
        runs = session.scalars(
            run_query.order_by(InvestmentAnalysisRun.requested_at.desc()).limit(5)
        ).all()
        role_cards["analyst"] = {
            "recent_runs": [
                {
                    "id": str(item.id),
                    "status": item.status,
                    "result_count": item.result_count,
                    "requested_at": item.requested_at.isoformat(),
                }
                for item in runs
            ],
            "active_or_failed_runs": session.scalar(
                select(func.count(InvestmentAnalysisRun.id)).where(
                    InvestmentAnalysisRun.workspace_id == principal.active_workspace_id,
                    InvestmentAnalysisRun.status.in_(
                        ["queued", "running", "failed", "cancel_requested"]
                    ),
                )
            )
            or 0,
            "locked_input_sets": session.scalar(
                select(func.count(InvestmentAnalysisInputSet.id)).where(
                    InvestmentAnalysisInputSet.workspace_id == principal.active_workspace_id,
                    InvestmentAnalysisInputSet.status == "LOCKED",
                )
            )
            or 0,
        }
    if "workspace.manage_members" in principal.effective_permissions:
        services = dependency_health()
        role_cards["admin"] = {
            "members": session.scalar(
                select(func.count(WorkspaceMembership.id)).where(
                    WorkspaceMembership.workspace_id == principal.active_workspace_id,
                    WorkspaceMembership.status == "active",
                )
            )
            or 0,
            "enabled_modules": len(principal.enabled_modules),
            "services": {"database": "ok", **services},
            "active_jobs": sum(item.status in {"QUEUED", "RUNNING"} for item in jobs),
            "failed_jobs": sum(item.status == "FAILED" for item in jobs),
            "scanner_mode": (
                "development_bypass"
                if APP_ENV in {"development", "test"} and ALLOW_INSECURE_DEV_FILE_SCAN
                else "fail_closed_or_operational"
            ),
        }
    if "apps.extension.use" in principal.effective_permissions:
        extension_query = select(ExtensionCase).where(
            ExtensionCase.workspace_id == principal.active_workspace_id
        )
        if "extension.case.view_workspace" not in principal.effective_permissions:
            extension_query = extension_query.where(
                or_(
                    ExtensionCase.created_by == principal.user_id,
                    ExtensionCase.current_assignee_id == principal.user_id,
                )
            )
        extension_cases = session.scalars(extension_query).all()
        visible_case_ids = [item.id for item in extension_cases]
        extension_card = {
            "assigned_cases": sum(
                item.current_assignee_id == principal.user_id for item in extension_cases
            ),
            "overdue_follow_ups": session.scalar(
                select(func.count(FollowUp.id)).where(
                    FollowUp.workspace_id == principal.active_workspace_id,
                    FollowUp.status == "OPEN",
                    FollowUp.due_date < func.current_date(),
                    FollowUp.case_id.in_(visible_case_ids or [UUID(int=0)]),
                )
            )
            or 0,
            "pending_sync": sum(item.sync_status != "SYNCED" for item in extension_cases),
        }
        if "extension.case.view_workspace" in principal.effective_permissions:
            extension_card["team_workload"] = {
                "assigned": sum(item.current_assignee_id is not None for item in extension_cases),
                "unassigned": sum(item.current_assignee_id is None for item in extension_cases),
                "open": sum(item.status not in {"CLOSED", "CANCELLED"} for item in extension_cases),
            }
            role_cards["extension_supervisor"] = extension_card
        else:
            role_cards["extension_officer"] = extension_card
    return {
        "workspace": {
            "id": str(principal.active_workspace_id),
            "name": principal.workspace_name,
        },
        "catalogue": {
            "visible_datasets": len(visible_datasets),
            "published_datasets": sum(
                item.current_published_version_id is not None for item in visible_datasets
            ),
            "real_samples": sum(
                item.licence_code == "UNCONFIRMED-SOURCE-LICENCE"
                for item in visible_datasets
            ),
            "recent": recent_datasets,
        },
        "jobs": {
            "active": sum(item.status in {"QUEUED", "RUNNING"} for item in jobs),
            "failed": sum(item.status == "FAILED" for item in jobs),
        },
        "role_cards": role_cards,
        "disclaimer": (
            "Real source samples, synthetic analysis data, illustrative methods and "
            "demonstration workflows are labelled separately and are not operational advice."
        ),
    }


@core_router.get("/api/search")
def platform_search(
    q: str = Query(min_length=2, max_length=200),
    page_size: int = Query(default=25, ge=1, le=50),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "workspace.view")
    term = f"%{q.strip()}%"
    results: list[dict[str, Any]] = []
    datasets = session.scalars(
        select(CatalogDataset).where(
            CatalogDataset.workspace_id == principal.active_workspace_id,
            CatalogDataset.lifecycle_status != "ARCHIVED",
            or_(
                CatalogDataset.title.ilike(term),
                CatalogDataset.abstract.ilike(term),
                CatalogDataset.slug.ilike(term),
            ),
        )
    ).all()
    for dataset in datasets:
        if not can_access_dataset(session, principal, dataset, "dataset.view_metadata"):
            continue
        results.append(
            {
                "type": "dataset",
                "id": str(dataset.id),
                "title": dataset.title,
                "subtitle": f"{dataset.data_kind} · {dataset.classification}",
                "path": f"/data/datasets/{dataset.id}",
            }
        )
    version_rows = session.execute(
        select(CatalogDatasetVersion, CatalogDataset)
        .join(CatalogDataset, CatalogDataset.id == CatalogDatasetVersion.dataset_id)
        .where(
            CatalogDataset.workspace_id == principal.active_workspace_id,
            or_(
                CatalogDatasetVersion.version_label.ilike(term),
                CatalogDatasetVersion.profile_key.ilike(term),
            ),
        )
        .limit(page_size)
    ).all()
    for version, dataset in version_rows:
        if not can_access_dataset(session, principal, dataset, "dataset.view_metadata"):
            continue
        results.append(
            {
                "type": "dataset_version",
                "id": str(version.id),
                "title": f"{dataset.title} · {version.version_label}",
                "subtitle": f"{version.profile_key} · {version.state}",
                "path": f"/data/datasets/{dataset.id}/versions/{version.id}",
            }
        )
    collections = session.scalars(
        select(Collection).where(
            Collection.workspace_id == principal.active_workspace_id,
            Collection.status == "ACTIVE",
            or_(Collection.title.ilike(term), Collection.description.ilike(term)),
        )
    ).all()
    results.extend(
        {
            "type": "collection",
            "id": str(item.id),
            "title": item.title,
            "subtitle": "Exact-version collection",
            "path": f"/data/collections/{item.id}",
        }
        for item in collections
    )
    if "apps.investment.use" in principal.effective_permissions:
        input_sets = session.scalars(
            select(InvestmentAnalysisInputSet).where(
                InvestmentAnalysisInputSet.workspace_id == principal.active_workspace_id,
                or_(
                    InvestmentAnalysisInputSet.name.ilike(term),
                    InvestmentAnalysisInputSet.label.ilike(term),
                ),
            )
        ).all()
        results.extend(
            {
                "type": "investment_input_set",
                "id": str(item.id),
                "title": item.label,
                "subtitle": f"{item.profile_mode} · {item.status}",
                "path": f"/apps/investment-prioritisation/input-sets/{item.id}",
            }
            for item in input_sets
            if item.created_by == principal.user_id
            or "investment.run.view" in principal.effective_permissions
        )
        try:
            run_id = UUID(q.strip())
        except ValueError:
            run_id = None
        if run_id:
            run = session.get(InvestmentAnalysisRun, run_id)
            if run and run.workspace_id == principal.active_workspace_id and (
                run.requested_by == principal.user_id
                or "investment.run.view" in principal.effective_permissions
            ):
                results.append(
                    {
                        "type": "investment_run",
                        "id": str(run.id),
                        "title": f"Investment run {str(run.id)[:8]}",
                        "subtitle": f"{run.status} · {run.result_count} results",
                        "path": f"/apps/investment-prioritisation/runs/{run.id}",
                    }
                )
    if "apps.extension.use" in principal.effective_permissions:
        extension_query = select(ExtensionCase).where(
            ExtensionCase.workspace_id == principal.active_workspace_id,
            or_(
                ExtensionCase.case_number.ilike(term),
                ExtensionCase.title.ilike(term),
                ExtensionCase.location_label.ilike(term),
            ),
        )
        if "extension.case.view_workspace" not in principal.effective_permissions:
            extension_query = extension_query.where(
                or_(
                    ExtensionCase.created_by == principal.user_id,
                    ExtensionCase.current_assignee_id == principal.user_id,
                )
            )
        extension_cases = session.scalars(extension_query).all()
        results.extend(
            {
                "type": "extension_case",
                "id": str(item.id),
                "title": f"{item.case_number} · {item.title}",
                "subtitle": f"{item.status} · {item.priority} · DEMONSTRATION",
                "path": f"/apps/extension-field-support/cases/{item.id}/summary",
            }
            for item in extension_cases
        )
        if "extension.knowledge.view" in principal.effective_permissions:
            knowledge = session.scalars(
                select(KnowledgeItem).where(
                    KnowledgeItem.workspace_id == principal.active_workspace_id,
                    KnowledgeItem.status == "ACTIVE",
                    or_(KnowledgeItem.title.ilike(term), KnowledgeItem.item_key.ilike(term)),
                )
            ).all()
            results.extend(
                {
                    "type": "extension_knowledge",
                    "id": str(item.id),
                    "title": item.title,
                    "subtitle": "Demonstration knowledge template",
                    "path": "/apps/extension-field-support/knowledge",
                }
                for item in knowledge
            )
    return {"query": q, "items": results[:page_size], "meta": {"returned": min(len(results), page_size)}}


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
    items: list[dict[str, Any]] = []
    for module, workspace_module in rows:
        last_activity = session.scalar(
            select(AuditEvent.event_time)
            .where(
                AuditEvent.workspace_id == principal.active_workspace_id,
                AuditEvent.action.ilike(f"{module.module_key.split('-')[0]}%"),
            )
            .order_by(AuditEvent.event_time.desc())
            .limit(1)
        )
        items.append(
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
                "owner": module.manifest.get("ownership", {}).get("product_owner"),
                "required_permission": (
                    module.manifest.get("permissions", {})
                    .get("required_to_enter", [None])[0]
                ),
                "last_activity": last_activity.isoformat() if last_activity else None,
            }
        )
    return {"items": items}


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
