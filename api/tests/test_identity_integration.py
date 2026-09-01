from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import DataCatalogItem, DataQualityCheck, DataVersion
from app.platform_models import (
    CatalogDataset,
    Group,
    GroupMembership,
    Module,
    Role,
    RoleAssignment,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceModule,
)
from app.platform_seed import DEV_ISSUER


client = TestClient(app)


def error_code(response) -> str:
    return response.json()["error"]["code"]


@pytest.mark.parametrize(
    ("user_status", "membership_status", "expires_at", "expected_code"),
    [
        ("inactive", "active", None, "IDENTITY_NOT_FOUND"),
        ("active", "suspended", None, "MEMBERSHIP_INACTIVE"),
        ("active", "active", datetime.now(timezone.utc) - timedelta(minutes=1), "MEMBERSHIP_INACTIVE"),
    ],
)
def test_inactive_or_expired_identity_context_is_denied(
    user_status: str,
    membership_status: str,
    expires_at: datetime | None,
    expected_code: str,
) -> None:
    subject = f"test-identity-{uuid4()}"
    with SessionLocal() as session:
        workspace = session.scalar(select(Workspace).order_by(Workspace.created_at))
        user = User(
            external_subject=subject,
            issuer=DEV_ISSUER,
            display_name="Temporary identity test",
            email=None,
            status=user_status,
            locale="en",
        )
        session.add(user)
        session.flush()
        session.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=user.id,
                status=membership_status,
                expires_at=expires_at,
            )
        )
        session.commit()
        user_id = user.id
    try:
        response = client.get("/api/me/capabilities", headers={"X-Dev-User-Subject": subject})
        assert response.status_code in {401, 403}
        assert error_code(response) == expected_code
    finally:
        with SessionLocal() as session:
            user = session.get(User, user_id)
            if user:
                session.delete(user)
                session.commit()


def test_disabled_module_denies_an_entitled_analyst() -> None:
    with SessionLocal() as session:
        workspace = session.scalar(select(Workspace).order_by(Workspace.created_at))
        module = session.scalar(select(Module).where(Module.module_key == "investment-prioritisation"))
        workspace_module = session.scalar(
            select(WorkspaceModule).where(
                WorkspaceModule.workspace_id == workspace.id,
                WorkspaceModule.module_id == module.id,
            )
        )
        original = workspace_module.enabled
        workspace_module.enabled = False
        session.commit()
    try:
        response = client.get("/api/catalog", headers={"X-Dev-User-Subject": "dev-analyst"})
        assert response.status_code == 403
        assert error_code(response) == "MODULE_DISABLED"
    finally:
        with SessionLocal() as session:
            workspace_module = session.scalar(
                select(WorkspaceModule).where(
                    WorkspaceModule.workspace_id == workspace.id,
                    WorkspaceModule.module_id == module.id,
                )
            )
            workspace_module.enabled = original
            session.commit()


def test_missing_application_entitlement_and_audit_scope_are_enforced() -> None:
    response = client.post(
        "/api/analysis/run",
        headers={"X-Dev-User-Subject": "dev-viewer"},
        json={"dataset_version_id": 1, "scenario_key": "balanced", "min_rice_area_ha": 750},
    )
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"

    response = client.get("/api/audit/v1/events", headers={"X-Dev-User-Subject": "dev-viewer"})
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"

    response = client.get("/api/audit/v1/events", headers={"X-Dev-User-Subject": "dev-auditor"})
    assert response.status_code == 200
    assert response.json()["meta"]["total"] >= 1


def test_reviewer_can_load_the_scoped_review_queue() -> None:
    response = client.get(
        "/api/data/v1/reviews",
        headers={"X-Dev-User-Subject": "dev-reviewer"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["items"], list)
    assert payload["meta"]["total"] == len(payload["items"])


def test_home_and_application_catalogue_are_api_backed() -> None:
    home = client.get("/api/home", headers={"X-Dev-User-Subject": "dev-admin"})
    assert home.status_code == 200
    payload = home.json()
    assert payload["workspace"]["name"]
    assert payload["catalogue"]["visible_datasets"] >= payload["catalogue"]["published_datasets"]
    assert {"contributor", "reviewer", "analyst", "admin"}.issubset(payload["role_cards"])
    assert "not operational advice" in payload["disclaimer"]

    modules = client.get("/api/modules", headers={"X-Dev-User-Subject": "dev-admin"})
    assert modules.status_code == 200
    investment = next(
        item for item in modules.json()["items"]
        if item["module_key"] == "investment-prioritisation"
    )
    assert investment["enabled"] is True
    assert investment["required_permission"] == "apps.investment.use"
    assert investment["owner"]


def test_global_search_does_not_disclose_a_private_dataset_to_an_unentitled_user() -> None:
    unique_term = f"hidden-search-{uuid4()}"
    with SessionLocal() as session:
        workspace = session.scalar(select(Workspace).order_by(Workspace.created_at))
        owner = session.scalar(select(User).where(User.external_subject == "dev-contributor"))
        dataset = CatalogDataset(
            workspace_id=workspace.id,
            slug=unique_term,
            title=unique_term,
            abstract="Temporary private search contract fixture.",
            data_kind="table",
            owner_user_id=owner.id,
            visibility="PRIVATE",
            classification="FAO_INTERNAL",
            created_by=owner.id,
            updated_by=owner.id,
        )
        session.add(dataset)
        session.commit()
        dataset_id = dataset.id
    try:
        response = client.get(
            f"/api/search?q={unique_term}",
            headers={"X-Dev-User-Subject": "dev-viewer"},
        )
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["meta"]["returned"] == 0
    finally:
        with SessionLocal() as session:
            dataset = session.get(CatalogDataset, dataset_id)
            if dataset:
                session.delete(dataset)
                session.commit()


def test_sensitive_field_dataset_requires_scoped_access_even_when_workspace_visible() -> None:
    with SessionLocal() as session:
        workspace = session.scalar(select(Workspace).order_by(Workspace.created_at))
        owner = session.scalar(select(User).where(User.external_subject == "dev-contributor"))
        dataset = CatalogDataset(
            workspace_id=workspace.id,
            slug=f"sensitive-access-test-{uuid4()}",
            title="Sensitive access test",
            abstract="Temporary sensitive dataset used to verify fail-closed discovery.",
            data_kind="vector",
            owner_user_id=owner.id,
            visibility="WORKSPACE",
            classification="SENSITIVE_FIELD",
            created_by=owner.id,
            updated_by=owner.id,
        )
        session.add(dataset)
        session.commit()
        dataset_id = dataset.id
        workspace_id = workspace.id
    try:
        response = client.get(
            f"/api/data/v1/datasets/{dataset_id}",
            headers={
                "X-Dev-User-Subject": "dev-viewer",
                "X-Workspace-Id": str(workspace_id),
            },
        )
        assert response.status_code == 404
        assert error_code(response) == "RESOURCE_NOT_FOUND"
    finally:
        with SessionLocal() as session:
            dataset = session.get(CatalogDataset, dataset_id)
            if dataset:
                session.delete(dataset)
                session.commit()


def test_group_membership_cannot_cross_workspace_authorization_boundary() -> None:
    suffix = str(uuid4())
    with SessionLocal() as session:
        workspace = session.scalar(select(Workspace).order_by(Workspace.created_at))
        viewer = session.scalar(select(User).where(User.external_subject == "dev-viewer"))
        publisher_role = session.scalar(
            select(Role).where(
                Role.workspace_id == workspace.id,
                Role.role_key == "data_publisher",
            )
        )
        other_workspace = Workspace(
            organization_id=workspace.organization_id,
            slug=f"boundary-test-{suffix}",
            name=f"Boundary test {suffix}",
            status="active",
        )
        session.add(other_workspace)
        session.flush()
        session.add(
            WorkspaceMembership(
                workspace_id=other_workspace.id,
                user_id=viewer.id,
                status="active",
            )
        )
        other_group = Group(
            workspace_id=other_workspace.id,
            slug=f"foreign-publishers-{suffix}",
            name="Foreign publishers",
        )
        session.add(other_group)
        session.flush()
        session.add(GroupMembership(group_id=other_group.id, user_id=viewer.id))
        assignment = RoleAssignment(
            subject_type="group",
            subject_id=other_group.id,
            role_id=publisher_role.id,
            scope_type="workspace",
            scope_id=workspace.id,
            valid_from=datetime.now(timezone.utc) - timedelta(minutes=1),
            reason="Cross-workspace boundary test",
        )
        session.add(assignment)
        session.commit()
        assignment_id = assignment.id
        other_workspace_id = other_workspace.id
        workspace_id = workspace.id
    try:
        response = client.get(
            "/api/me/capabilities",
            headers={
                "X-Dev-User-Subject": "dev-viewer",
                "X-Workspace-Id": str(workspace_id),
            },
        )
        assert response.status_code == 200
        assert "dataset.publish" not in response.json()["effective_permissions"]
    finally:
        with SessionLocal() as session:
            assignment = session.get(RoleAssignment, assignment_id)
            if assignment:
                session.delete(assignment)
                session.flush()
            other_workspace = session.get(Workspace, other_workspace_id)
            if other_workspace:
                session.delete(other_workspace)
            session.commit()


def test_legacy_catalog_mutations_are_read_only_and_create_no_dual_writes() -> None:
    with SessionLocal() as session:
        before = (
            session.scalar(select(func.count(DataCatalogItem.id))),
            session.scalar(select(func.count(DataVersion.id))),
            session.scalar(select(func.count(DataQualityCheck.id))),
        )

    response = client.post(
        "/api/data-catalog/upload",
        headers={"X-Dev-User-Subject": "dev-contributor"},
        files={"file": ("legacy.geojson", b'{"type":"FeatureCollection","features":[]}', "application/geo+json")},
        data={
            "dataset_name": "Must not be written",
            "description": "Legacy endpoint read-only contract test.",
            "version_label": "never-created",
        },
    )
    assert response.status_code == 410
    assert error_code(response) == "LEGACY_CATALOG_READ_ONLY"

    response = client.post(
        "/api/data-versions/1/publish",
        headers={"X-Dev-User-Subject": "dev-publisher"},
    )
    assert response.status_code == 410
    assert error_code(response) == "LEGACY_CATALOG_READ_ONLY"

    with SessionLocal() as session:
        after = (
            session.scalar(select(func.count(DataCatalogItem.id))),
            session.scalar(select(func.count(DataVersion.id))),
            session.scalar(select(func.count(DataQualityCheck.id))),
        )
    assert after == before

    response = client.get(
        "/api/data-catalog",
        headers={"X-Dev-User-Subject": "dev-contributor"},
    )
    assert response.status_code == 200
    assert response.json()["datasets"][0]["versions"][0]["status"] == "published"
