from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select

from app.audit_service import record_event
from app.database import SessionLocal
from app.investment.engine import score_priority_areas
from app.investment.input_loader import prepare_run_inputs
from app.investment.metrics import increment
from app.investment.service import materialise_results, register_output, stable_output_id
from app.jobs import _set_step, celery_app
from app.object_store import remove_object
from app.platform_models import (
    InvestmentAnalysisRun,
    InvestmentAnalysisRunInput,
    InvestmentMethodVersion,
    InvestmentPriorityResult,
    JobStep,
    ProcessingJob,
)


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cancel_if_requested(session, run_id: UUID, job_id: UUID) -> bool:
    session.expire_all()
    run = session.get(InvestmentAnalysisRun, run_id)
    job = session.get(ProcessingJob, job_id)
    if run is None or job is None or run.status != "cancel_requested":
        return False
    session.execute(delete(InvestmentPriorityResult).where(InvestmentPriorityResult.run_id == run.id))
    run.result_count = 0
    run.result_checksum = None
    run.status = "cancelled"
    run.progress = min(run.progress, 99)
    run.current_step = "cancelled"
    run.completed_at = _now()
    job.status = "CANCELLED"
    job.completed_at = run.completed_at
    record_event(
        session,
        action="investment.analysis.cancel",
        resource_type="analysis_run",
        resource_id=run.id,
        outcome="success",
        correlation_id=run.correlation_id,
        actor_id=run.requested_by,
        workspace_id=run.workspace_id,
        after={"status": "cancelled"},
    )
    session.commit()
    return True


def _cleanup_unregistered_outputs(run: InvestmentAnalysisRun) -> None:
    if run.output_dataset_version_id:
        return
    dataset_id = stable_output_id("output-dataset", f"{run.workspace_id}:{run.input_set_id}")
    version_id = stable_output_id("output-version", str(run.id))
    prefix = f"catalog/{run.workspace_id}/datasets/{dataset_id}/versions/{version_id}/derived"
    for filename in ("priority-ranking.csv", "priority-ranking.geojson", "run-manifest.json"):
        remove_object(f"{prefix}/{filename}")


@celery_app.task(name="investment:run-prioritisation:v1", bind=True, max_retries=0)
def run_prioritisation(self, run_id: str, job_id: str) -> dict:
    run_uuid, job_uuid = UUID(run_id), UUID(job_id)
    started = _now()
    increment("investment_runs_total")
    with SessionLocal() as session:
        run = session.get(InvestmentAnalysisRun, run_uuid)
        job = session.get(ProcessingJob, job_uuid)
        if run is None or job is None:
            return {"status": "missing"}
        if run.status in {"succeeded", "succeeded_with_warnings"}:
            return {"status": run.status, "run_id": str(run.id), "result_checksum": run.result_checksum}
        if _cancel_if_requested(session, run_uuid, job_uuid):
            return {"status": "cancelled"}
        run.status = "running"
        run.started_at = run.started_at or started
        run.current_step = "validate-inputs"
        run.progress = 3
        job.status = "RUNNING"
        job.started_at = job.started_at or started
        job.attempt += 1
        job.progress = 3
        record_event(
            session,
            action="investment.analysis.start",
            resource_type="analysis_run",
            resource_id=run.id,
            outcome="success",
            correlation_id=run.correlation_id,
            actor_id=run.requested_by,
            workspace_id=run.workspace_id,
            after={"job_id": str(job.id), "attempt": job.attempt},
        )
        session.commit()

        try:
            _set_step(session, job.id, "validate-inputs", "RUNNING")
            inputs = session.scalars(
                select(InvestmentAnalysisRunInput)
                .where(InvestmentAnalysisRunInput.run_id == run.id)
                .order_by(InvestmentAnalysisRunInput.ordinal)
            ).all()
            method = session.get(InvestmentMethodVersion, run.method_version_id)
            if not inputs or method is None or method.checksum != run.method_checksum:
                raise RuntimeError("RUN_SNAPSHOT_INVALID")
            _set_step(session, job.id, "validate-inputs", "SUCCEEDED", inputs=len(inputs))
            run.progress = job.progress = 15
            session.commit()
            if _cancel_if_requested(session, run_uuid, job_uuid):
                return {"status": "cancelled"}

            run.current_step = "prepare"
            _set_step(session, job.id, "prepare", "RUNNING")
            prepared = prepare_run_inputs(list(inputs))
            _set_step(session, job.id, "prepare", "SUCCEEDED", areas=len(prepared))
            run.progress = job.progress = 35
            session.commit()
            if _cancel_if_requested(session, run_uuid, job_uuid):
                return {"status": "cancelled"}

            run.current_step = "score"
            _set_step(session, job.id, "score", "RUNNING")
            results = score_priority_areas(prepared, method.specification_json, run.parameters_snapshot)
            _set_step(session, job.id, "score", "SUCCEEDED", results=len(results))
            run.progress = job.progress = 55
            session.commit()
            if _cancel_if_requested(session, run_uuid, job_uuid):
                return {"status": "cancelled"}

            run.current_step = "materialise-results"
            _set_step(session, job.id, "materialise-results", "RUNNING")
            checksum = materialise_results(session, run, results)
            session.commit()
            _set_step(session, job.id, "materialise-results", "SUCCEEDED", checksum=checksum, rows=len(results))
            run.progress = job.progress = 75
            session.commit()
            if _cancel_if_requested(session, run_uuid, job_uuid):
                return {"status": "cancelled"}

            run.current_step = "register-output"
            run.completed_at = _now()
            _set_step(session, job.id, "register-output", "RUNNING")
            try:
                output = register_output(session, run, correlation_id=run.correlation_id)
            except Exception:
                increment("investment_output_registration_failures_total")
                raise
            registered_step = session.scalar(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_key == "register-output")
            )
            if registered_step:
                registered_step.status = "SUCCEEDED"
                registered_step.completed_at = _now()
                registered_step.details_json = {"dataset_version_id": output["dataset_version_id"]}
            run.progress = job.progress = 93

            run.current_step = "finalise"
            final_step = session.scalar(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_key == "finalise")
            )
            if final_step:
                final_step.status = "RUNNING"
                final_step.started_at = _now()
            completed = _now()
            run.completed_at = completed
            run.status = "succeeded_with_warnings" if run.warnings_json else "succeeded"
            run.progress = 100
            run.current_step = "complete"
            job.status = "SUCCEEDED"
            job.progress = 100
            job.completed_at = completed
            job.result_json = {
                "run_id": str(run.id),
                "status": run.status,
                "result_count": run.result_count,
                "result_checksum": run.result_checksum,
                "output_dataset_version_id": str(run.output_dataset_version_id),
            }
            duration = (completed - started).total_seconds()
            increment("investment_run_duration_seconds", duration)
            record_event(
                session,
                action="investment.analysis.complete",
                resource_type="analysis_run",
                resource_id=run.id,
                outcome="success",
                correlation_id=run.correlation_id,
                actor_id=run.requested_by,
                workspace_id=run.workspace_id,
                after={"status": run.status, "result_count": run.result_count, "result_checksum": run.result_checksum},
            )
            record_event(
                session,
                action="investment.analysis.completed.v1",
                resource_type="analysis_run",
                resource_id=run.id,
                outcome="success",
                correlation_id=run.correlation_id,
                actor_id=run.requested_by,
                workspace_id=run.workspace_id,
                after={"run_id": str(run.id), "output_dataset_version_id": str(run.output_dataset_version_id)},
            )
            if final_step:
                final_step.status = "SUCCEEDED"
                final_step.completed_at = completed
                final_step.details_json = {"status": run.status}
            session.commit()
            return job.result_json
        except Exception as error:
            session.rollback()
            run = session.get(InvestmentAnalysisRun, run_uuid)
            job = session.get(ProcessingJob, job_uuid)
            if run is None or job is None:
                return {"status": "failed", "error_code": "RUN_NOT_FOUND"}
            _cleanup_unregistered_outputs(run)
            code = str(error) if str(error).isupper() and " " not in str(error) else "INVESTMENT_ANALYSIS_FAILED"
            run.status = "failed"
            run.current_step = "failed"
            run.completed_at = _now()
            run.failure_json = {
                "code": code,
                "message": "Investment analysis failed. Inspect the structured job and audit evidence.",
                "details": {"exception_type": type(error).__name__},
                "correlation_id": run.correlation_id,
            }
            job.status = "FAILED"
            job.error_code = code
            job.error_message = run.failure_json["message"]
            job.completed_at = run.completed_at
            running_step = session.scalar(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.status == "RUNNING")
            )
            if running_step:
                running_step.status = "FAILED"
                running_step.completed_at = run.completed_at
                running_step.details_json = {"error_code": code}
            increment("investment_run_failures_total")
            record_event(
                session,
                action="investment.analysis.fail",
                resource_type="analysis_run",
                resource_id=run.id,
                outcome="failure",
                correlation_id=run.correlation_id,
                actor_id=run.requested_by,
                workspace_id=run.workspace_id,
                reason=code,
                after={"status": "failed", "failure_code": code},
                severity="ERROR",
            )
            record_event(
                session,
                action="investment.analysis.failed.v1",
                resource_type="analysis_run",
                resource_id=run.id,
                outcome="failure",
                correlation_id=run.correlation_id,
                actor_id=run.requested_by,
                workspace_id=run.workspace_id,
                after={"run_id": str(run.id), "failure_code": code},
                severity="ERROR",
            )
            session.commit()
            logger.exception("investment.analysis.failed", extra={"correlation_id": run.correlation_id, "run_id": str(run.id)})
            return {"status": "failed", "error_code": code}
