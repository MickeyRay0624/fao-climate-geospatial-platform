from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import forbidden, not_found
from app.identity import Principal
from app.platform_models import CatalogDataset, CatalogDatasetVersion, PermissionGrant, ReviewRequest


def assert_permission(principal: Principal, permission_code: str, module_key: str | None = None) -> None:
    if module_key and module_key not in principal.enabled_modules:
        raise forbidden("MODULE_DISABLED", "This module is not enabled in the active workspace.")
    if permission_code not in principal.effective_permissions:
        raise forbidden()


def _grant_effects(
    session: Session,
    principal: Principal,
    dataset: CatalogDataset,
    permission_code: str,
) -> set[str]:
    now = datetime.now(timezone.utc)
    subjects = [principal.user_id, *principal.group_ids]
    return set(
        session.scalars(
            select(PermissionGrant.effect).where(
                PermissionGrant.workspace_id == principal.active_workspace_id,
                PermissionGrant.subject_id.in_(subjects),
                PermissionGrant.resource_type.in_(["dataset", "dataset_version"]),
                PermissionGrant.resource_id == dataset.id,
                PermissionGrant.permission_code == permission_code,
                or_(PermissionGrant.expires_at.is_(None), PermissionGrant.expires_at > now),
            )
        ).all()
    )


def can_access_dataset(
    session: Session,
    principal: Principal,
    dataset: CatalogDataset,
    permission_code: str,
) -> bool:
    if dataset.workspace_id != principal.active_workspace_id:
        return False
    effects = _grant_effects(session, principal, dataset, permission_code)
    if "DENY" in effects:
        return False
    if permission_code not in principal.effective_permissions and "ALLOW" not in effects:
        return False
    if permission_code in {"dataset.edit_metadata", "dataset.upload_version", "dataset.submit_review", "dataset.manage_access"}:
        return dataset.owner_user_id == principal.user_id or "workspace_admin" in principal.role_keys or "ALLOW" in effects
    if permission_code in {"dataset.view_metadata", "dataset.preview", "dataset.download", "lineage.view"}:
        if dataset.owner_user_id == principal.user_id or "ALLOW" in effects:
            return True
        # Private resources become visible only inside the review/publish work scope.
        # Explicit DENY was evaluated above and therefore still takes precedence.
        if "data_reviewer" in principal.role_keys:
            scoped_review = session.scalar(
                select(ReviewRequest.id)
                .join(CatalogDatasetVersion, CatalogDatasetVersion.id == ReviewRequest.dataset_version_id)
                .where(
                    CatalogDatasetVersion.dataset_id == dataset.id,
                    ReviewRequest.status.in_(["OPEN", "IN_PROGRESS"]),
                    or_(
                        ReviewRequest.reviewer_group_id.is_(None),
                        ReviewRequest.reviewer_group_id.in_(principal.group_ids),
                    ),
                )
                .limit(1)
            )
            if scoped_review:
                return True
        if "data_publisher" in principal.role_keys:
            publishable_version = session.scalar(
                select(CatalogDatasetVersion.id)
                .where(
                    CatalogDatasetVersion.dataset_id == dataset.id,
                    CatalogDatasetVersion.state.in_(["APPROVED", "PUBLISHED"]),
                )
                .limit(1)
            )
            if publishable_version:
                return True
        # Sensitive field data never becomes workspace-discoverable merely from
        # visibility; it needs ownership, an explicit grant, or a scoped action.
        if (
            dataset.classification != "SENSITIVE_FIELD"
            and dataset.visibility in {"WORKSPACE", "TEAM", "FAO_INTERNAL", "PUBLIC"}
        ):
            return True
        if "workspace_admin" in principal.role_keys and dataset.classification != "SENSITIVE_FIELD":
            return True
        return False
    return True


def require_dataset_access(
    session: Session,
    principal: Principal,
    dataset: CatalogDataset | None,
    permission_code: str,
) -> CatalogDataset:
    if dataset is None or not can_access_dataset(session, principal, dataset, permission_code):
        raise not_found("Dataset")
    return dataset
