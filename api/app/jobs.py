from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID

from celery import Celery
from sqlalchemy import func, select

from app.audit_service import record_event
from app.config import (
    ALLOW_INSECURE_DEV_FILE_SCAN,
    APP_ENV,
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
    CELERY_TASK_ALWAYS_EAGER,
)
from app.database import SessionLocal
from app.models import AdminArea
from app.object_store import copy_object, get_bytes, remove_object
from app.platform_models import (
    CatalogAsset,
    CatalogDataset,
    CatalogDatasetVersion,
    JobStep,
    LineageEdge,
    LineageProcess,
    ProcessingJob,
    QualityIssue,
    QualityProfile,
    QualityRun,
    Representation,
    UploadSession,
    UploadSessionFile,
)
from app.datahub.validators import DevelopmentBypassScanner, FailClosedScanner, validate_file


logger = logging.getLogger(__name__)
celery_app = Celery("fao-climate-platform", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
celery_app.conf.update(
    task_always_eager=CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=False,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "catalog:validate-version:v1": {"queue": "celery"},
        "investment:run-prioritisation:v1": {"queue": "geospatial-analysis"},
    },
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _set_step(session, job_id: UUID, step_key: str, status: str, **details) -> None:
    step = session.scalar(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_key == step_key)
    )
    if step is None:
        return
    step.status = status
    if status == "RUNNING" and step.started_at is None:
        step.started_at = _now()
    if status in {"SUCCEEDED", "FAILED", "SKIPPED"}:
        step.completed_at = _now()
    if details:
        step.details_json = details
    session.commit()


def _profile(session, profile_key: str) -> QualityProfile:
    key, version = profile_key.split("@", 1)
    profile = session.scalar(
        select(QualityProfile).where(
            QualityProfile.profile_key == key,
            QualityProfile.profile_version == version,
            QualityProfile.active.is_(True),
        )
    )
    if profile is None:
        raise RuntimeError(f"Validation profile {profile_key} is not installed")
    return profile


def _ingest_priority_bundle(session, version: CatalogDatasetVersion, parsed) -> None:
    existing = session.scalar(
        select(func.count(AdminArea.id)).where(AdminArea.catalog_version_id == version.id)
    ) or 0
    if existing:
        return
    # The legacy helper sets the integer FK. A tiny adapter object keeps the old
    # read model while the authoritative version remains catalog.dataset_versions.
    class VersionAdapter:
        id = None

    for record in parsed.records:
        from geoalchemy2.shape import from_shape
        from app.models import IndicatorValue

        area = AdminArea(
            dataset_version_id=None,
            catalog_version_id=version.id,
            code=record.code,
            name=record.name,
            province=record.province,
            population=record.population,
            rice_area_ha=record.rice_area_ha,
            data_quality=record.data_quality,
            geom=from_shape(record.geometry, srid=4326),
        )
        for code, value in record.indicators.items():
            area.indicator_values.append(
                IndicatorValue(
                    indicator_code=code,
                    value=value,
                    quality_flag="uploaded-missing" if value is None else "uploaded",
                )
            )
        session.add(area)


@celery_app.task(name="catalog:validate-version:v1", bind=True, max_retries=0)
def process_upload_session(self, upload_session_id: str, job_id: str, correlation_id: str) -> dict:
    upload_uuid, job_uuid = UUID(upload_session_id), UUID(job_id)
    with SessionLocal() as session:
        job = session.get(ProcessingJob, job_uuid)
        upload = session.get(UploadSession, upload_uuid)
        if job is None or upload is None:
            return {"status": "missing"}
        if job.status == "SUCCEEDED":
            return job.result_json
        version = session.get(CatalogDatasetVersion, upload.dataset_version_id)
        if version is None:
            return {"status": "missing-version"}
        dataset = session.get(CatalogDataset, version.dataset_id)
        job.status = "RUNNING"
        job.started_at = _now()
        job.attempt += 1
        job.progress = 4
        session.commit()

        try:
            files = session.scalars(
                select(UploadSessionFile)
                .where(UploadSessionFile.upload_session_id == upload.id)
                .order_by(UploadSessionFile.filename)
            ).all()
            _set_step(session, job.id, "inspect", "RUNNING")
            payloads: list[tuple[UploadSessionFile, bytes, str]] = []
            for item in files:
                payload = get_bytes(item.quarantine_object_key)
                digest = hashlib.sha256(payload).hexdigest()
                if item.expected_sha256 and digest != item.expected_sha256:
                    raise RuntimeError("CHECKSUM_MISMATCH")
                if len(payload) != item.expected_size:
                    raise RuntimeError("UPLOAD_SIZE_MISMATCH")
                payloads.append((item, payload, digest))
            _set_step(session, job.id, "inspect", "SUCCEEDED", files=len(payloads))
            job.progress = 20
            session.commit()

            _set_step(session, job.id, "scan", "RUNNING")
            scanner = (
                DevelopmentBypassScanner()
                if APP_ENV in {"development", "test"} and ALLOW_INSECURE_DEV_FILE_SCAN
                else FailClosedScanner()
            )
            scanned: list[tuple[UploadSessionFile, bytes, str, str]] = []
            for item, payload, digest in payloads:
                scanned.append((item, payload, digest, scanner.scan(item.filename, payload)))
            _set_step(
                session,
                job.id,
                "scan",
                "SUCCEEDED",
                mode="development_bypass" if ALLOW_INSECURE_DEV_FILE_SCAN else "approved_scanner",
            )
            job.progress = 36
            session.commit()

            _set_step(session, job.id, "validate", "RUNNING")
            profile = _profile(session, version.profile_key)
            results = [
                (item, payload, digest, scan_status, validate_file(version.profile_key, item.filename, payload, item.media_type))
                for item, payload, digest, scan_status in scanned
            ]
            quality_run = QualityRun(
                dataset_version_id=version.id,
                quality_profile_id=profile.id,
                engine_version="platform-validator/1.0",
                status="RUNNING",
                started_at=_now(),
            )
            session.add(quality_run)
            session.flush()
            issue_count = 0
            blocking_count = 0
            warning_count = 0
            for _, _, _, _, result in results:
                for issue in result.issues:
                    issue_count += 1
                    blocking_count += int(issue.severity == "BLOCKING")
                    warning_count += int(issue.severity == "WARNING")
                    session.add(
                        QualityIssue(
                            quality_run_id=quality_run.id,
                            code=issue.code,
                            name=issue.name,
                            severity=issue.severity,
                            affected_count=issue.affected_count,
                            details_json={"message": issue.message, **issue.details},
                        )
                    )
            quality_run.status = "FAILED" if blocking_count else ("WARNING" if warning_count else "PASSED")
            quality_run.completed_at = _now()
            quality_run.summary_json = {
                "files": len(results),
                "issues": issue_count,
                "blocking": blocking_count,
                "warnings": warning_count,
                "record_count": sum(result.record_count for *_, result in results),
                "scan_mode": "development_bypass" if ALLOW_INSECURE_DEV_FILE_SCAN else "approved_scanner",
            }
            _set_step(
                session,
                job.id,
                "validate",
                "SUCCEEDED",
                quality_status=quality_run.status,
                issues=issue_count,
            )
            job.progress = 62
            session.commit()

            _set_step(session, job.id, "register", "RUNNING")
            for item, payload, digest, scan_status, result in results:
                existing_asset = session.scalar(
                    select(CatalogAsset).where(
                        CatalogAsset.dataset_version_id == version.id,
                        CatalogAsset.sha256 == digest,
                        CatalogAsset.role == "source",
                    )
                )
                final_key = item.quarantine_object_key
                if not result.has_blocking:
                    final_key = (
                        f"catalog/{upload.workspace_id}/datasets/{dataset.id}/"
                        f"versions/{version.id}/source/{item.id}"
                    )
                    copy_object(item.quarantine_object_key, final_key)
                    remove_object(item.quarantine_object_key)
                if existing_asset is None:
                    asset = CatalogAsset(
                        dataset_version_id=version.id,
                        role="source",
                        filename=item.filename,
                        object_key=final_key,
                        media_type=item.media_type,
                        size_bytes=len(payload),
                        sha256=digest,
                        upload_session_id=upload.id,
                        scan_status=scan_status,
                    )
                    session.add(asset)
                if session.scalar(
                    select(Representation.id).where(
                        Representation.dataset_version_id == version.id,
                        Representation.representation_type == result.representation_type,
                    )
                ) is None:
                    session.add(
                        Representation(
                            dataset_version_id=version.id,
                            representation_type=result.representation_type,
                            locator=final_key,
                            status="READY" if not result.has_blocking else "FAILED",
                            crs=result.crs,
                            geometry_type=result.geometry_type,
                            bbox_json=result.bbox,
                            schema_json=result.schema,
                            statistics_json={"record_count": result.record_count},
                            preview_json=result.preview,
                        )
                    )
                if version.profile_key == "analysis-ready-priority-bundle@1.0" and not result.has_blocking:
                    _ingest_priority_bundle(session, version, result.parsed_bundle)

            process = LineageProcess(
                workspace_id=upload.workspace_id,
                process_type="ingestion",
                module_key="data-hub",
                external_run_type="processing_job",
                external_run_id=str(job.id),
                method_identifier=version.profile_key,
                method_version="1.0",
                parameters_json={"upload_session_id": str(upload.id), "scan_bypass": ALLOW_INSECURE_DEV_FILE_SCAN},
                status="SUCCEEDED" if not blocking_count else "FAILED",
                completed_at=_now(),
            )
            session.add(process)
            session.flush()
            session.add(
                LineageEdge(
                    process_id=process.id,
                    direction="OUTPUT",
                    dataset_version_id=version.id,
                    role="validated-version",
                    ordinal=0,
                )
            )
            version.state = "VALIDATION_FAILED" if blocking_count else "VALIDATED"
            job.status = "SUCCEEDED"
            job.progress = 100
            job.completed_at = _now()
            job.result_json = {
                "dataset_version_id": str(version.id),
                "validation_status": quality_run.status,
                "quality_run_id": str(quality_run.id),
                "record_count": quality_run.summary_json["record_count"],
            }
            _set_step(session, job.id, "register", "SUCCEEDED", version_state=version.state)
            record_event(
                session,
                action="catalog.version.processing.complete",
                resource_type="dataset_version",
                resource_id=version.id,
                outcome="success",
                correlation_id=correlation_id,
                actor_id=upload.created_by,
                workspace_id=upload.workspace_id,
                after={"state": version.state, "quality_status": quality_run.status},
            )
            session.commit()
            return job.result_json
        except Exception as error:
            session.rollback()
            job = session.get(ProcessingJob, job_uuid)
            version = session.get(CatalogDatasetVersion, upload.dataset_version_id)
            if job is not None:
                job.status = "FAILED"
                job.error_code = str(error) if str(error).isupper() else "PROCESSING_FAILED"
                job.error_message = "Processing failed; source objects remain in quarantine."
                job.completed_at = _now()
            if version is not None and version.state == "PROCESSING":
                version.state = "VALIDATION_FAILED"
            failed_step = session.scalar(
                select(JobStep).where(JobStep.job_id == job_uuid, JobStep.status == "RUNNING")
            )
            if failed_step:
                failed_step.status = "FAILED"
                failed_step.completed_at = _now()
                failed_step.details_json = {"error_code": job.error_code if job else "PROCESSING_FAILED"}
            record_event(
                session,
                action="catalog.version.processing.failure",
                resource_type="dataset_version",
                resource_id=upload.dataset_version_id,
                outcome="failure",
                correlation_id=correlation_id,
                actor_id=upload.created_by,
                workspace_id=upload.workspace_id,
                reason=job.error_code if job else "PROCESSING_FAILED",
                severity="ERROR",
            )
            session.commit()
            logger.exception("Data Hub processing failed", extra={"correlation_id": correlation_id})
            return {"status": "failed", "error_code": job.error_code if job else "PROCESSING_FAILED"}


# Import after celery_app and the shared step helper are defined. The worker is
# launched with app.jobs:celery_app, so this explicit registration is required.
from app.investment import tasks as investment_tasks  # noqa: E402,F401
