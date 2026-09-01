from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, Request
from jwt import PyJWKClient
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import (
    ALLOW_DEV_IDENTITY_HEADERS,
    AUTH_MODE,
    DEFAULT_DEV_USER_SUBJECT,
    OIDC_AUDIENCE,
    OIDC_ISSUER,
    OIDC_JWKS_URL,
)
from app.database import get_session
from app.errors import PlatformError
from app.platform_models import (
    Group,
    GroupMembership,
    Module,
    Permission,
    Role,
    RoleAssignment,
    RolePermission,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceModule,
)


@dataclass(slots=True)
class Principal:
    user_id: UUID
    external_subject: str
    issuer: str
    display_name: str
    email: str | None
    active_workspace_id: UUID
    workspace_name: str
    workspace_memberships: list[dict[str, Any]]
    group_ids: set[UUID] = field(default_factory=set)
    role_keys: set[str] = field(default_factory=set)
    effective_permissions: set[str] = field(default_factory=set)
    enabled_modules: set[str] = field(default_factory=set)
    dev_auth: bool = False


def _load_principal(
    session: Session,
    user: User,
    requested_workspace_id: UUID | None,
    *,
    dev_auth: bool,
) -> Principal:
    now = datetime.now(timezone.utc)
    memberships = session.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.status == "active",
            Workspace.status == "active",
            or_(WorkspaceMembership.expires_at.is_(None), WorkspaceMembership.expires_at > now),
        )
        .order_by(Workspace.name)
    ).all()
    if not memberships:
        raise PlatformError("MEMBERSHIP_INACTIVE", "No active workspace membership is available.", 403)
    selected = next(
        ((membership, workspace) for membership, workspace in memberships if workspace.id == requested_workspace_id),
        memberships[0] if requested_workspace_id is None else None,
    )
    if selected is None:
        raise PlatformError("WORKSPACE_ACCESS_DENIED", "The requested workspace is unavailable.", 403)
    _, workspace = selected

    group_ids = set(
        session.scalars(
            select(GroupMembership.group_id)
            .join(Group, Group.id == GroupMembership.group_id)
            .where(
                GroupMembership.user_id == user.id,
                Group.workspace_id == workspace.id,
            )
        ).all()
    )
    assignments = session.execute(
        select(RoleAssignment, Role)
        .join(Role, Role.id == RoleAssignment.role_id)
        .where(
            or_(
                and_(RoleAssignment.subject_type == "user", RoleAssignment.subject_id == user.id),
                and_(RoleAssignment.subject_type == "group", RoleAssignment.subject_id.in_(group_ids)),
            ),
            RoleAssignment.scope_id == workspace.id,
            or_(Role.workspace_id.is_(None), Role.workspace_id == workspace.id),
            RoleAssignment.valid_from <= now,
            or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until > now),
        )
    ).all()
    role_ids = [assignment.role_id for assignment, _ in assignments]
    permissions = set()
    if role_ids:
        permissions = set(
            session.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id.in_(role_ids))
            ).all()
        )
    modules = set(
        session.scalars(
            select(Module.module_key)
            .join(WorkspaceModule, WorkspaceModule.module_id == Module.id)
            .where(
                WorkspaceModule.workspace_id == workspace.id,
                WorkspaceModule.enabled.is_(True),
                Module.manifest_valid.is_(True),
                Module.status == "installed",
            )
        ).all()
    )
    return Principal(
        user_id=user.id,
        external_subject=user.external_subject,
        issuer=user.issuer,
        display_name=user.display_name,
        email=user.email,
        active_workspace_id=workspace.id,
        workspace_name=workspace.name,
        workspace_memberships=[
            {"workspace_id": str(item_workspace.id), "name": item_workspace.name, "status": item_membership.status}
            for item_membership, item_workspace in memberships
        ],
        group_ids=group_ids,
        role_keys={role.role_key for _, role in assignments},
        effective_permissions=permissions,
        enabled_modules=modules,
        dev_auth=dev_auth,
    )


def _dev_user(session: Session, subject: str) -> User:
    user = session.scalar(
        select(User).where(User.issuer == "urn:fao:climate-platform:dev", User.external_subject == subject)
    )
    if user is None or user.status != "active":
        raise PlatformError("IDENTITY_NOT_FOUND", "Development identity is not available.", 401)
    return user


def _oidc_user(session: Session, authorization: str | None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise PlatformError("AUTHENTICATION_REQUIRED", "A valid bearer token is required.", 401)
    token = authorization.split(" ", 1)[1]
    try:
        signing_key = PyJWKClient(OIDC_JWKS_URL).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256", "ES256"],
            audience=OIDC_AUDIENCE,
            issuer=OIDC_ISSUER,
        )
    except Exception as error:
        raise PlatformError("INVALID_IDENTITY_TOKEN", "The identity token could not be validated.", 401) from error
    user = session.scalar(
        select(User).where(User.issuer == claims["iss"], User.external_subject == claims["sub"])
    )
    if user is None or user.status != "active":
        raise PlatformError("IDENTITY_NOT_PROVISIONED", "The identity is not provisioned for this platform.", 403)
    return user


def get_current_principal(
    request: Request,
    session: Session = Depends(get_session),
    x_dev_user_subject: str | None = Header(default=None, alias="X-Dev-User-Subject"),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal:
    requested_workspace = None
    if x_workspace_id:
        try:
            requested_workspace = UUID(x_workspace_id)
        except ValueError as error:
            raise PlatformError("INVALID_WORKSPACE_ID", "Workspace ID must be a UUID.", 400) from error
    if AUTH_MODE == "dev":
        if not ALLOW_DEV_IDENTITY_HEADERS and x_dev_user_subject:
            raise PlatformError("DEV_IDENTITY_DISABLED", "Development identity headers are disabled.", 401)
        if not ALLOW_DEV_IDENTITY_HEADERS:
            raise PlatformError("AUTHENTICATION_REQUIRED", "OIDC authentication is required.", 401)
        user = _dev_user(session, x_dev_user_subject or DEFAULT_DEV_USER_SUBJECT)
        principal = _load_principal(session, user, requested_workspace, dev_auth=True)
    else:
        user = _oidc_user(session, authorization)
        principal = _load_principal(session, user, requested_workspace, dev_auth=False)
    request.state.principal = principal
    return principal
