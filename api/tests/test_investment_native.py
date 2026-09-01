from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.investment.constants import LEGACY_METHOD_SPEC, METHOD_IMPLEMENTATION_KEY
from app.main import app
from app.models import AnalysisRun as LegacyAnalysisRun
from app.models import PriorityResult as LegacyPriorityResult
from app.platform_models import (
    InvestmentAnalysisRun,
    InvestmentAnalysisRunInput,
    InvestmentAnalysisInputSet,
    InvestmentMethodDefinition,
    InvestmentMethodVersion,
    InvestmentPriorityResult,
    InvestmentScenario,
    IdempotencyRecord,
    JobStep,
    LegacyIdMapping,
    ProcessingJob,
)


client = TestClient(app)
BASE = "/api/apps/investment-prioritisation/v1"
ANALYST = {"X-Dev-User-Subject": "dev-analyst"}


def _successful_run_ids(minimum: int) -> list:
    with SessionLocal() as session:
        existing = session.scalars(
            select(InvestmentAnalysisRun.id)
            .where(
                InvestmentAnalysisRun.status.in_(
                    ["succeeded", "succeeded_with_warnings"]
                )
            )
            .order_by(InvestmentAnalysisRun.completed_at, InvestmentAnalysisRun.id)
        ).all()
    if len(existing) >= minimum:
        return existing[:minimum]

    input_sets = client.get(
        f"{BASE}/input-sets?page_size=100", headers=ANALYST
    ).json()["items"]
    input_set = next(
        item
        for item in input_sets
        if item["status"] == "LOCKED" and item["readiness"]["ready"]
    )
    scenarios = client.get(
        f"{BASE}/scenarios?page_size=100", headers=ANALYST
    ).json()["items"]
    scenario = next(item for item in scenarios if item["scenario_key"] == "balanced")
    body = {
        "input_set_id": input_set["id"],
        "method_version_id": scenario["method_version_id"],
        "scenario_id": scenario["id"],
        "run_mode": "FORMAL",
        "overrides": {},
    }
    from app.investment.tasks import run_prioritisation

    for _ in range(minimum - len(existing)):
        with patch("app.investment.router.run_prioritisation.delay"):
            response = client.post(
                f"{BASE}/runs",
                headers={
                    **ANALYST,
                    "Idempotency-Key": f"pytest-success-evidence-{uuid4()}",
                },
                json=body,
            )
        assert response.status_code == 202
        created = response.json()
        outcome = run_prioritisation.run(
            created["id"], created["processing_job_id"]
        )
        assert outcome["status"] in {"succeeded", "succeeded_with_warnings"}

    with SessionLocal() as session:
        return session.scalars(
            select(InvestmentAnalysisRun.id)
            .where(
                InvestmentAnalysisRun.status.in_(
                    ["succeeded", "succeeded_with_warnings"]
                )
            )
            .order_by(InvestmentAnalysisRun.completed_at, InvestmentAnalysisRun.id)
            .limit(minimum)
        ).all()


def test_overview_is_read_only_and_backfill_reconciles_exactly() -> None:
    with SessionLocal() as session:
        before = session.scalar(select(func.count(InvestmentAnalysisRun.id)))
        legacy_runs = session.scalar(select(func.count(LegacyAnalysisRun.id))) or 0
        legacy_results = session.scalar(select(func.count(LegacyPriorityResult.id))) or 0
    response = client.get(f"{BASE}/overview", headers=ANALYST)
    assert response.status_code == 200
    assert response.json()["native_write_authority"] == "investment.*"
    with SessionLocal() as session:
        after = session.scalar(select(func.count(InvestmentAnalysisRun.id)))
        migrated_runs = session.scalar(
            select(func.count(InvestmentAnalysisRun.id)).where(
                InvestmentAnalysisRun.migration_source == "investment-native-phase-2a/1.0"
            )
        )
        migrated_results = session.scalar(
            select(func.count(InvestmentPriorityResult.id))
            .join(InvestmentAnalysisRun, InvestmentAnalysisRun.id == InvestmentPriorityResult.run_id)
            .where(InvestmentAnalysisRun.migration_source == "investment-native-phase-2a/1.0")
        )
        mappings = session.scalar(
            select(func.count(LegacyIdMapping.id)).where(
                LegacyIdMapping.entity_type == "priority_results"
            )
        )
    assert after == before
    assert (legacy_runs, legacy_results) in {(0, 0), (13, 1443)}
    assert (migrated_runs, migrated_results, mappings) == (
        legacy_runs,
        legacy_results,
        legacy_results,
    )


def test_legacy_analysis_command_is_gone_and_never_dual_writes() -> None:
    with SessionLocal() as session:
        before = (
            session.scalar(select(func.count(LegacyAnalysisRun.id))),
            session.scalar(select(func.count(LegacyPriorityResult.id))),
        )
    response = client.post(
        "/api/analysis/run",
        headers=ANALYST,
        json={"dataset_version_id": 1, "scenario_key": "balanced", "min_rice_area_ha": 750},
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "LEGACY_ANALYSIS_READ_ONLY"
    with SessionLocal() as session:
        after = (
            session.scalar(select(func.count(LegacyAnalysisRun.id))),
            session.scalar(select(func.count(LegacyPriorityResult.id))),
        )
    assert before in {(0, 0), (13, 1443)}
    assert after == before


def test_real_pilot_readiness_is_incomplete_and_read_only() -> None:
    with SessionLocal() as session:
        before = (
            session.scalar(select(func.count(InvestmentAnalysisRun.id))),
            session.scalar(select(func.count(InvestmentPriorityResult.id))),
        )
    response = client.get(f"{BASE}/readiness", headers=ANALYST)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready_to_run"] is False
    if payload["boundary_available"]:
        assert payload["available_indicator_roles"] == ["poverty_index"]
        assert set(payload["missing_required_roles"]) == {
            "yield_gap",
            "drought_risk",
            "flood_risk",
            "irrigation_gap",
            "market_isolation",
            "nbs_opportunity",
        }
        assert payload["record_coverage"]["boundary_records"] == 26
        assert payload["record_coverage"]["poverty_records"] == 26
    else:
        assert payload["available_indicator_roles"] == []
        assert set(payload["missing_required_roles"]) == {
            "administrative_boundary",
            "yield_gap",
            "drought_risk",
            "flood_risk",
            "poverty_index",
            "irrigation_gap",
            "market_isolation",
            "nbs_opportunity",
        }
        assert payload["record_coverage"]["boundary_records"] == 0
        assert payload["record_coverage"]["poverty_records"] == 0
        assert "BOUNDARY_MISSING" in payload["reason_codes"]
    assert "LICENCE_NOT_CONFIRMED" in payload["reason_codes"]
    with SessionLocal() as session:
        after = (
            session.scalar(select(func.count(InvestmentAnalysisRun.id))),
            session.scalar(select(func.count(InvestmentPriorityResult.id))),
        )
    assert after == before


def test_incomplete_input_set_cannot_lock_or_create_run() -> None:
    suffix = uuid4().hex
    create_key = f"pytest-incomplete-create-{suffix}"
    lock_key = f"pytest-incomplete-lock-{suffix}"
    run_key = f"pytest-incomplete-run-{suffix}"
    headers = {**ANALYST, "Idempotency-Key": create_key}
    created = client.post(
        f"{BASE}/input-sets",
        headers=headers,
        json={
            "name": f"incomplete-{suffix}",
            "label": "Temporary incomplete readiness test",
            "profile_mode": "SEPARATE_LAYERS",
            "study_area_ref": {},
            "run_mode_compatibility": ["FORMAL"],
        },
    )
    assert created.status_code == 201
    item = created.json()
    try:
        with SessionLocal() as session:
            before = (
                session.scalar(select(func.count(InvestmentAnalysisRun.id))),
                session.scalar(select(func.count(InvestmentPriorityResult.id))),
            )
        lock = client.post(
            f"{BASE}/input-sets/{item['id']}/lock",
            headers={**ANALYST, "Idempotency-Key": lock_key},
            json={"reason": "Negative readiness contract test.", "row_version": item["row_version"]},
        )
        assert lock.status_code == 409
        assert lock.json()["error"]["code"] == "INPUT_SET_NOT_READY"

        scenario = next(
            value
            for value in client.get(f"{BASE}/scenarios?page_size=100", headers=ANALYST).json()["items"]
            if value["scenario_key"] == "balanced"
        )
        rejected = client.post(
            f"{BASE}/runs",
            headers={**ANALYST, "Idempotency-Key": run_key},
            json={
                "input_set_id": item["id"],
                "method_version_id": scenario["method_version_id"],
                "scenario_id": scenario["id"],
                "run_mode": "FORMAL",
                "overrides": {},
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "LOCKED_INPUT_SET_REQUIRED"
        with SessionLocal() as session:
            after = (
                session.scalar(select(func.count(InvestmentAnalysisRun.id))),
                session.scalar(select(func.count(InvestmentPriorityResult.id))),
            )
        assert after == before
    finally:
        with SessionLocal() as session:
            session.query(IdempotencyRecord).filter(
                IdempotencyRecord.idempotency_key.in_([create_key, lock_key, run_key])
            ).delete(synchronize_session=False)
            exact = session.get(InvestmentAnalysisInputSet, item["id"])
            if exact:
                session.delete(exact)
            session.commit()


def test_run_create_freezes_snapshot_and_enforces_idempotency(monkeypatch) -> None:
    monkeypatch.setattr("app.investment.router.run_prioritisation.delay", lambda *args: None)
    inputs = client.get(f"{BASE}/input-sets?page_size=100", headers=ANALYST).json()["items"]
    scenarios = client.get(f"{BASE}/scenarios?page_size=100", headers=ANALYST).json()["items"]
    input_set = next(item for item in inputs if item["status"] == "LOCKED")
    scenario = next(item for item in scenarios if item["scenario_key"] == "balanced")
    body = {
        "input_set_id": input_set["id"],
        "method_version_id": scenario["method_version_id"],
        "scenario_id": scenario["id"],
        "run_mode": "FORMAL",
        "overrides": {},
    }
    key = f"pytest-native-{uuid4()}"
    headers = {**ANALYST, "Idempotency-Key": key}
    first = client.post(f"{BASE}/runs", headers=headers, json=body)
    second = client.post(f"{BASE}/runs", headers=headers, json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    run_id = first.json()["id"]
    with SessionLocal() as session:
        run = session.get(InvestmentAnalysisRun, run_id)
        snapshots = session.scalar(
            select(func.count(InvestmentAnalysisRunInput.id)).where(
                InvestmentAnalysisRunInput.run_id == run.id
            )
        )
        assert run.status == "queued"
        assert run.processing_job_id is not None
        job_id = run.processing_job_id
        assert snapshots == len(input_set["members"])
        assert run.input_set_checksum == input_set["checksum"]
        assert run.method_checksum and run.scenario_checksum and run.request_hash

    different = {**body, "overrides": {"min_rice_area_ha": 800}}
    conflict = client.post(f"{BASE}/runs", headers=headers, json=different)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    cancelled = client.post(
        f"{BASE}/runs/{run_id}/cancel",
        headers={**ANALYST, "Idempotency-Key": f"pytest-cancel-{uuid4()}"},
        json={"reason": "Exercise the safe queued cancellation path."},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancel_requested"
    from app.investment.tasks import run_prioritisation

    outcome = run_prioritisation.run(run_id, str(job_id))
    assert outcome["status"] == "cancelled"

    # This queued test record can be removed without touching governed successful evidence.
    with SessionLocal() as session:
        run = session.get(InvestmentAnalysisRun, run_id)
        session.query(JobStep).filter_by(job_id=job_id).delete()
        session.delete(run)
        session.flush()
        job = session.get(ProcessingJob, job_id)
        if job:
            session.delete(job)
        session.commit()


def test_failure_is_structured_and_failed_job_can_be_requeued(monkeypatch) -> None:
    monkeypatch.setattr("app.investment.router.run_prioritisation.delay", lambda *args: None)
    monkeypatch.setattr("app.investment.tasks.run_prioritisation.delay", lambda *args: None)
    inputs = client.get(f"{BASE}/input-sets?page_size=100", headers=ANALYST).json()["items"]
    scenarios = client.get(f"{BASE}/scenarios?page_size=100", headers=ANALYST).json()["items"]
    input_set = next(item for item in inputs if item["status"] == "LOCKED")
    scenario = next(item for item in scenarios if item["scenario_key"] == "balanced")
    response = client.post(
        f"{BASE}/runs",
        headers={**ANALYST, "Idempotency-Key": f"pytest-failure-{uuid4()}"},
        json={
            "input_set_id": input_set["id"],
            "method_version_id": scenario["method_version_id"],
            "scenario_id": scenario["id"],
            "run_mode": "FORMAL",
            "overrides": {},
        },
    )
    assert response.status_code == 202
    run_id = response.json()["id"]
    job_id = response.json()["processing_job_id"]
    with SessionLocal() as session:
        session.query(InvestmentAnalysisRunInput).filter_by(run_id=run_id).delete()
        session.commit()

    from app.investment.tasks import run_prioritisation

    outcome = run_prioritisation.run(run_id, job_id)
    assert outcome == {"status": "failed", "error_code": "RUN_SNAPSHOT_INVALID"}
    failed = client.get(f"{BASE}/runs/{run_id}", headers=ANALYST)
    assert failed.status_code == 200
    assert failed.json()["failure"]["code"] == "RUN_SNAPSHOT_INVALID"
    assert "traceback" not in str(failed.json()).lower()

    retried = client.post(
        f"/api/jobs/v1/jobs/{job_id}/retry",
        headers={"X-Dev-User-Subject": "dev-admin"},
        json={"reason": "Verify durable investment retry transition."},
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "QUEUED"

    with SessionLocal() as session:
        session.query(JobStep).filter_by(job_id=job_id).delete()
        run = session.get(InvestmentAnalysisRun, run_id)
        session.delete(run)
        session.flush()
        job = session.get(ProcessingJob, job_id)
        if job:
            session.delete(job)
        session.commit()


def test_method_creator_cannot_self_approve() -> None:
    admin = {"X-Dev-User-Subject": "dev-admin"}
    suffix = uuid4().hex[:12]
    method = client.post(
        f"{BASE}/methods",
        headers={**admin, "Idempotency-Key": f"pytest-method-{suffix}"},
        json={
            "method_key": f"pytest-sod-{suffix}",
            "name": "Pytest separation method",
            "description": "Temporary record for creator/approver separation verification.",
        },
    )
    assert method.status_code == 201
    version = client.post(
        f"{BASE}/methods/{method.json()['id']}/versions",
        headers={**admin, "Idempotency-Key": f"pytest-method-version-{suffix}"},
        json={
            "version_label": "1.0.0",
            "specification": LEGACY_METHOD_SPEC,
            "implementation_key": METHOD_IMPLEMENTATION_KEY,
            "code_ref": "pytest/separation-of-duties",
            "container_metadata": {},
            "validation_evidence": {"purpose": "negative-control"},
            "disclaimer": "Synthetic verification only; not an endorsed method.",
        },
    )
    assert version.status_code == 201
    submitted = client.post(
        f"{BASE}/method-versions/{version.json()['id']}/submit",
        headers={**admin, "Idempotency-Key": f"pytest-method-submit-{suffix}"},
        json={"reason": "Submit for separation verification.", "row_version": version.json()["row_version"]},
    )
    assert submitted.status_code == 200
    denied = client.post(
        f"{BASE}/method-versions/{version.json()['id']}/approve",
        headers={**admin, "Idempotency-Key": f"pytest-method-approve-{suffix}"},
        json={"reason": "Creator must not approve.", "row_version": submitted.json()["row_version"]},
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "SEPARATION_OF_DUTIES"

    with SessionLocal() as session:
        item = session.get(InvestmentMethodVersion, version.json()["id"])
        definition = session.get(InvestmentMethodDefinition, method.json()["id"])
        session.delete(item)
        session.flush()
        session.delete(definition)
        session.commit()


def test_database_guards_protect_approved_and_successful_evidence() -> None:
    with SessionLocal() as session:
        scenario = session.scalar(
            select(InvestmentScenario).where(InvestmentScenario.state == "APPROVED")
        )
        scenario.name = "Forbidden mutation"
        with pytest.raises(DBAPIError, match="approved scenarios are immutable"):
            session.flush()
        session.rollback()

    with SessionLocal() as session:
        method = session.scalar(
            select(InvestmentMethodVersion).where(InvestmentMethodVersion.state == "APPROVED")
        )
        method.checksum = "0" * 64
        with pytest.raises(DBAPIError, match="approved method versions are immutable"):
            session.flush()
        session.rollback()

    run_id = _successful_run_ids(1)[0]
    with SessionLocal() as session:
        run = session.get(InvestmentAnalysisRun, run_id)
        run.progress = 99
        with pytest.raises(DBAPIError, match="successful investment runs are immutable"):
            session.flush()
        session.rollback()


def test_migrated_fixed_sentinel_and_assets_are_authorised() -> None:
    with SessionLocal() as session:
        run = session.scalar(
            select(InvestmentAnalysisRun).where(InvestmentAnalysisRun.legacy_run_id == 1)
        )
        if run is None:
            run_id = _successful_run_ids(1)[0]
            run = session.get(InvestmentAnalysisRun, run_id)
        assert run is not None
        top = session.scalar(
            select(InvestmentPriorityResult).where(
                InvestmentPriorityResult.run_id == run.id,
                InvestmentPriorityResult.rank == 1,
            )
        )
        run_id = run.id
    assert top is not None
    assert top.area_name == "Prey Veng Demo Commune 03"
    assert top.score == 65.32

    allowed = client.get(f"{BASE}/runs/{run_id}/assets", headers=ANALYST)
    assert allowed.status_code == 200
    assert len(allowed.json()["items"]) == 3
    assert all("url" in item and "object_key" not in item for item in allowed.json()["items"])

    denied = client.get(
        f"{BASE}/runs/{run_id}/assets",
        headers={"X-Dev-User-Subject": "dev-contributor"},
    )
    assert denied.status_code == 403


def test_comparison_is_explicit_and_creates_no_analysis_run() -> None:
    with SessionLocal() as session:
        run_ids = session.scalars(
            select(InvestmentAnalysisRun.id)
            .where(InvestmentAnalysisRun.migration_source == "investment-native-phase-2a/1.0")
            .order_by(InvestmentAnalysisRun.legacy_run_id)
            .limit(2)
        ).all()
    if len(run_ids) < 2:
        run_ids = _successful_run_ids(2)
    assert len(run_ids) == 2
    with SessionLocal() as session:
        before = session.scalar(select(func.count(InvestmentAnalysisRun.id)))
    response = client.post(
        f"{BASE}/comparisons",
        headers={**ANALYST, "Idempotency-Key": f"pytest-compare-{uuid4()}"},
        json={"left_run_id": str(run_ids[0]), "right_run_id": str(run_ids[1]), "top_n": 20},
    )
    assert response.status_code == 201
    assert response.json()["summary"]["area_count"] == 111
    with SessionLocal() as session:
        after = session.scalar(select(func.count(InvestmentAnalysisRun.id)))
    assert after == before
