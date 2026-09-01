from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, get_session
from app.extension_models import (
    ActivityPlan,
    CaseStatusHistory,
    ExtensionCase,
    MediaAsset,
    Observation,
    VerificationTemplateVersion,
)
from app.main import app
from app.platform_models import AuditEvent, CatalogDataset, User


BASE = "/api/apps/extension-field-support/v1"
OFFICER_1 = {"X-Dev-User-Subject": "dev-extension-officer-1"}
OFFICER_2 = {"X-Dev-User-Subject": "dev-extension-officer-2"}
SUPERVISOR = {"X-Dev-User-Subject": "dev-extension-supervisor"}
ADMIN = {"X-Dev-User-Subject": "dev-admin"}


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


def _key(prefix: str) -> str:
    return f"pytest-extension-{prefix}-{uuid4()}"


def _create_and_assign(client: TestClient, session: Session):
    created = client.post(
        f"{BASE}/cases",
        headers={**OFFICER_1, "Idempotency-Key": _key("case")},
        json={
            "title": "Temporary isolated extension workflow test",
            "crop": "Rice",
            "growth_stage": "Tillering",
            "severity": "MODERATE",
            "affected_area_ha": 0.5,
            "location_label": "Fictional isolated test zone",
            "priority": "NORMAL",
            "notes": "No personal identity or exact real location.",
        },
    )
    assert created.status_code == 201
    officer = session.scalar(
        select(User).where(User.external_subject == "dev-extension-officer-1")
    )
    assigned = client.post(
        f"{BASE}/cases/{created.json()['id']}/assign",
        headers={**SUPERVISOR, "Idempotency-Key": _key("assign")},
        json={
            "officer_id": str(officer.id),
            "priority": "HIGH",
            "reason": "Isolated transition and idempotency verification.",
            "row_version": created.json()["row_version"],
        },
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "ASSIGNED"
    return assigned.json()


def test_officer_scope_and_supervisor_workspace_scope() -> None:
    client = TestClient(app)
    officer = client.get(f"{BASE}/cases", headers=OFFICER_1)
    supervisor = client.get(f"{BASE}/cases", headers=SUPERVISOR)
    assert officer.status_code == supervisor.status_code == 200
    assert officer.json()["meta"]["total"] == 3
    assert supervisor.json()["meta"]["total"] == 8
    assert all(
        value["assignee"]["display_name"] == "Sreypov Mom"
        for value in officer.json()["items"]
    )


def test_case_state_machine_and_observation_idempotency(isolated_client) -> None:
    client, session = isolated_client
    assigned = _create_and_assign(client, session)
    illegal = client.post(
        f"{BASE}/cases/{assigned['id']}/transition",
        headers={**OFFICER_1, "Idempotency-Key": _key("illegal")},
        json={
            "target_status": "IN_VERIFICATION",
            "reason": "Attempt to skip required states.",
            "row_version": assigned["row_version"],
        },
    )
    assert illegal.status_code == 409
    assert illegal.json()["error"]["code"] == "EXTENSION_CASE_TRANSITION_INVALID"

    client_uuid = str(uuid4())
    body = {
        "client_uuid": client_uuid,
        "status": "COMPLETED",
        "observed_at": "2026-09-01T10:00:00Z",
        "severity": "MODERATE",
        "affected_area_ha": 0.5,
        "approximate_location": "Fictional isolated test zone",
        "notes": "A structured, manual observation for idempotency verification.",
        "structured": {"automatic_interpretation": False},
    }
    mutation_key = _key("observation")
    first = client.post(
        f"{BASE}/cases/{assigned['id']}/observations",
        headers={**OFFICER_1, "Idempotency-Key": mutation_key},
        json=body,
    )
    second = client.post(
        f"{BASE}/cases/{assigned['id']}/observations",
        headers={**OFFICER_1, "Idempotency-Key": mutation_key},
        json=body,
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert session.scalar(
        select(func.count(Observation.id)).where(Observation.client_uuid == client_uuid)
    ) == 1
    case = client.get(f"{BASE}/cases/{assigned['id']}", headers=OFFICER_1)
    assert case.json()["status"] == "IN_OBSERVATION"

    sync = client.post(
        f"{BASE}/sync",
        headers={**OFFICER_1, "Idempotency-Key": _key("sync")},
        json={
            "items": [
                {
                    "client_uuid": client_uuid,
                    "mutation_type": "observation.create",
                    "case_id": assigned["id"],
                    "payload": body,
                }
            ]
        },
    )
    assert sync.status_code == 200
    assert sync.json()["items"][0]["status"] == "DUPLICATE_ACKNOWLEDGED"


def test_verification_creates_new_revisions(isolated_client) -> None:
    client, session = isolated_client
    case = session.scalar(
        select(ExtensionCase).where(ExtensionCase.case_number == "DEMO-003")
    )
    template = session.scalar(select(VerificationTemplateVersion))
    first = client.post(
        f"{BASE}/cases/{case.id}/verifications",
        headers={**OFFICER_2, "Idempotency-Key": _key("verification-1")},
        json={"template_version_id": str(template.id)},
    )
    second = client.post(
        f"{BASE}/cases/{case.id}/verifications",
        headers={**OFFICER_2, "Idempotency-Key": _key("verification-2")},
        json={"template_version_id": str(template.id)},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["revision_number"] == 1
    assert second.json()["revision_number"] == 2
    assert first.json()["id"] != second.json()["id"]


def test_knowledge_and_activity_separation_of_duties(isolated_client) -> None:
    client, session = isolated_client
    knowledge = client.get(f"{BASE}/knowledge", headers=ADMIN).json()["items"][0]
    created = client.post(
        f"{BASE}/knowledge/{knowledge['id']}/versions",
        headers={**ADMIN, "Idempotency-Key": _key("knowledge-create")},
        json={
            "content": {"purpose": "Temporary draft; not advice."},
            "source_summary": "Temporary placeholder source for separation verification.",
        },
    )
    assert created.status_code == 201
    draft = next(value for value in created.json()["versions"] if value["status"] == "DRAFT")
    denied = client.post(
        f"{BASE}/knowledge-versions/{draft['id']}/approve",
        headers={**ADMIN, "Idempotency-Key": _key("knowledge-approve")},
        json={
            "reason": "Creator must not approve the same version.",
            "row_version": draft["row_version"],
        },
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "EXTENSION_SEPARATION_OF_DUTIES"

    admin = session.scalar(select(User).where(User.external_subject == "dev-admin"))
    activity = ActivityPlan(
        workspace_id=session.scalar(select(ExtensionCase.workspace_id)),
        case_id=None,
        activity_type="demo",
        objective="Temporary activity separation fixture.",
        participant_count=0,
        responsible_officer_id=admin.id,
        due_date=date(2026, 9, 20),
        status="PENDING_APPROVAL",
        created_by=admin.id,
    )
    session.add(activity)
    session.flush()
    denied_activity = client.post(
        f"{BASE}/activities/{activity.id}/approval",
        headers={**ADMIN, "Idempotency-Key": _key("activity-approve")},
        json={
            "decision": "APPROVE",
            "reason": "Creator must not approve the same activity.",
            "row_version": 1,
        },
    )
    assert denied_activity.status_code == 409
    assert denied_activity.json()["error"]["code"] == "EXTENSION_SEPARATION_OF_DUTIES"


def test_unauthorised_media_is_hidden_and_denial_is_audited(isolated_client) -> None:
    client, session = isolated_client
    case = session.scalar(
        select(ExtensionCase).where(ExtensionCase.case_number == "DEMO-001")
    )
    media = MediaAsset(
        workspace_id=case.workspace_id,
        case_id=case.id,
        object_key=f"extension/{case.workspace_id}/cases/{case.id}/media/{uuid4()}.jpg",
        filename="restricted-test.jpg",
        media_type="image/jpeg",
        size_bytes=4,
        sha256="a" * 64,
        scan_status="CLEAN",
        created_by=case.created_by,
    )
    session.add(media)
    session.flush()
    denied = client.get(f"{BASE}/media/{media.id}/view", headers=OFFICER_2)
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    with SessionLocal() as audit_session:
        audit = audit_session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.action == "security.access.denied",
                AuditEvent.resource_id == f"{BASE}/media/{media.id}/view",
            )
            .order_by(AuditEvent.event_time.desc())
        )
        assert audit is not None
        assert audit.outcome == "denied"


def test_raw_case_workflow_never_registers_a_catalog_dataset(isolated_client) -> None:
    client, session = isolated_client
    before = session.scalar(select(func.count(CatalogDataset.id)))
    created = client.post(
        f"{BASE}/cases",
        headers={**OFFICER_1, "Idempotency-Key": _key("catalog-boundary")},
        json={
            "title": "Raw extension domain boundary fixture",
            "crop": "Rice",
            "growth_stage": "Not recorded",
            "severity": "LOW",
            "location_label": "Fictional test zone",
            "priority": "LOW",
            "notes": "No Data Hub registration is authorised.",
        },
    )
    assert created.status_code == 201
    after = session.scalar(select(func.count(CatalogDataset.id)))
    assert after == before


def test_completed_records_and_status_history_are_database_immutable() -> None:
    with SessionLocal() as session:
        observation = session.scalar(
            select(Observation).where(Observation.status == "COMPLETED")
        )
        observation.notes = "Forbidden completed observation mutation"
        with pytest.raises(DBAPIError, match="completed extension records are immutable"):
            session.flush()
        session.rollback()

    with SessionLocal() as session:
        history = session.scalar(select(CaseStatusHistory))
        history.reason = "Forbidden append-only history mutation"
        with pytest.raises(DBAPIError, match="extension history is append-only"):
            session.flush()
        session.rollback()
