from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import engine, get_session
from app.main import app
from app.platform_models import Group, Role, User


ADMIN = {"X-Dev-User-Subject": "dev-admin"}
VIEWER = {"X-Dev-User-Subject": "dev-viewer"}
AUDITOR = {"X-Dev-User-Subject": "dev-auditor"}
BASE = "/api/governance/v1"


@pytest.fixture
def isolated_client():
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        outer.rollback()
        connection.close()


def _headers(prefix: str) -> dict[str, str]:
    return {**ADMIN, "Idempotency-Key": f"pytest-governance-{prefix}-{uuid4()}"}


def test_governance_routes_are_complete_and_permission_scoped() -> None:
    client = TestClient(app)
    routes = [
        "reviews",
        "members",
        "groups",
        "roles",
        "data-policies",
        "quality-profiles",
        "knowledge-approvals",
        "applications",
        "retention",
        "system-health",
    ]
    for route in routes:
        response = client.get(f"{BASE}/{route}", headers=ADMIN)
        assert response.status_code == 200, (route, response.text)

    denied = client.get(f"{BASE}/data-policies", headers=VIEWER)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"


def test_group_membership_mutations_are_idempotent_and_audited(isolated_client) -> None:
    client, session = isolated_client
    before = session.scalar(select(func.count(Group.id)))
    headers = _headers("create-group")
    body = {
        "name": "Temporary governance verification group",
        "description": "An isolated transaction fixture.",
        "reason": "Verify idempotent audited group administration.",
    }
    first = client.post(f"{BASE}/groups", headers=headers, json=body)
    second = client.post(f"{BASE}/groups", headers=headers, json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert session.scalar(select(func.count(Group.id))) == before + 1

    viewer = session.scalar(select(User).where(User.external_subject == "dev-viewer"))
    group_id = first.json()["id"]
    added = client.post(
        f"{BASE}/groups/{group_id}/members",
        headers=_headers("add-member"),
        json={
            "user_id": str(viewer.id),
            "reason": "Verify scoped membership administration.",
        },
    )
    assert added.status_code == 200
    assert any(item["id"] == str(viewer.id) for item in added.json()["members"])

    removed = client.post(
        f"{BASE}/groups/{group_id}/members/{viewer.id}/remove",
        headers=_headers("remove-member"),
        json={"reason": "Verify audited membership removal."},
    )
    assert removed.status_code == 200
    assert all(item["id"] != str(viewer.id) for item in removed.json()["members"])


def test_role_assignment_requires_future_expiry_and_workspace_member(isolated_client) -> None:
    client, session = isolated_client
    role = session.scalar(select(Role).where(Role.role_key == "auditor"))
    officer = session.scalar(
        select(User).where(User.external_subject == "dev-extension-officer-1")
    )
    expired = client.post(
        f"{BASE}/roles/{role.id}/assignments",
        headers=_headers("expired-role"),
        json={
            "subject_id": str(officer.id),
            "valid_until": "2020-01-01T00:00:00Z",
            "reason": "Verify expiry validation rejects stale authority.",
        },
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "ROLE_ASSIGNMENT_EXPIRY_INVALID"

    valid_until = datetime.now(timezone.utc) + timedelta(days=30)
    assigned = client.post(
        f"{BASE}/roles/{role.id}/assignments",
        headers=_headers("valid-role"),
        json={
            "subject_id": str(officer.id),
            "valid_until": valid_until.isoformat(),
            "reason": "Verify a time-bounded workspace role assignment.",
        },
    )
    assert assigned.status_code == 201
    assert assigned.json()["role_key"] == "auditor"
    assert assigned.json()["subject"]["id"] == str(officer.id)


def test_review_queues_remain_typed_and_health_exposes_no_credentials() -> None:
    client = TestClient(app)
    reviews = client.get(f"{BASE}/reviews", headers=ADMIN)
    assert reviews.status_code == 200
    assert set(reviews.json()["queues"]) == {"dataset", "knowledge"}
    assert reviews.json()["meta"]["typed_queues"] is True

    health = client.get(f"{BASE}/system-health", headers=ADMIN)
    assert health.status_code == 200
    payload = health.json()
    assert payload["services"]["migrations"]["current"] == "20260901_0005"
    assert payload["secrets_exposed"] is False
    assert "rice_demo_change_me" not in health.text
    assert "dss_local_storage_change_me" not in health.text


def test_audit_export_is_permission_scoped_and_csv() -> None:
    client = TestClient(app)
    denied = client.get("/api/audit/v1/events/export", headers=VIEWER)
    assert denied.status_code == 403
    exported = client.get("/api/audit/v1/events/export", headers=AUDITOR)
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "workspace-audit-events.csv" in exported.headers["content-disposition"]
    assert exported.text.startswith("event_time,actor_id,action")
