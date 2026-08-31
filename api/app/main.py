from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from collections import defaultdict
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.analysis import calculate_priorities, normalise_weights
from app.catalog import INDICATORS, SCENARIOS
from app.config import (
    ALLOW_INSECURE_DEV_FILE_SCAN,
    AUTH_MODE,
    CORS_ORIGINS,
    DEMO_DISCLAIMER,
)
from app.audit_service import record_event
from app.authorization import assert_permission
from app.data_management import (
    available_analysis_versions,
    catalog_payload,
    serialise_version,
)
from app.database import SessionLocal, get_session
from app.errors import PlatformError
from app.identity import Principal, get_current_principal
from app.logging_config import configure_logging
from app.models import (
    AdminArea,
    AnalysisRun,
    DataVersion,
    Dataset,
    IndicatorValue,
    PriorityResult,
)
from app.object_store import ensure_bucket, get_bytes
from app.schemas import AnalysisRequest
from app.datahub.router import router as datahub_router
from app.platform_router import (
    audit_router,
    core_router,
    dependency_health,
    governance_router,
    jobs_router,
)


configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FAO Climate Geospatial Data & Decision Platform API",
    version="1.0.0-phase1",
    description=(
        "Versioned spatial data management and transparent multi-criteria analysis "
        "for a local demonstrator."
    ),
)

app.include_router(core_router)
app.include_router(datahub_router)
app.include_router(jobs_router)
app.include_router(audit_router)
app.include_router(governance_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    supplied = request.headers.get("X-Correlation-ID", "")
    request.state.correlation_id = (
        supplied[:64] if supplied and re_safe_correlation(supplied) else str(uuid.uuid4())
    )
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    logger.info(
        "request.complete",
        extra={
            "correlation_id": request.state.correlation_id,
            "action": f"{request.method} {request.url.path}",
        },
    )
    return response


def re_safe_correlation(value: str) -> bool:
    return len(value) <= 64 and all(character.isalnum() or character in "-_." for character in value)


def error_envelope(request: Request, code: str, message: str, details: dict[str, Any], status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "correlation_id": getattr(request.state, "correlation_id", "unknown"),
            }
        },
    )


@app.exception_handler(PlatformError)
async def platform_error_handler(request: Request, error: PlatformError) -> JSONResponse:
    principal = getattr(request.state, "principal", None)
    if principal is not None and error.status_code in {403, 404}:
        try:
            with SessionLocal() as audit_session:
                record_event(
                    audit_session,
                    action="security.access.denied",
                    resource_type="api_route",
                    resource_id=request.url.path,
                    outcome="denied",
                    correlation_id=getattr(request.state, "correlation_id", "unknown"),
                    actor_id=principal.user_id,
                    workspace_id=principal.active_workspace_id,
                    reason=error.code,
                    after={"method": request.method},
                    severity="WARNING",
                )
                audit_session.commit()
        except Exception:
            logger.exception(
                "security.denial_audit_failed",
                extra={"correlation_id": getattr(request.state, "correlation_id", "unknown")},
            )
    return error_envelope(request, error.code, error.message, error.details, error.status_code)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
    code = {400: "BAD_REQUEST", 401: "AUTHENTICATION_REQUIRED", 403: "FORBIDDEN", 404: "RESOURCE_NOT_FOUND", 409: "CONFLICT"}.get(error.status_code, "HTTP_ERROR")
    message = error.detail if isinstance(error.detail, str) else "The request could not be completed."
    details = error.detail if isinstance(error.detail, dict) else {}
    return error_envelope(request, code, message, details, error.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    details = {"issues": [{"location": list(item["loc"]), "message": item["msg"], "type": item["type"]} for item in error.errors()]}
    return error_envelope(request, "REQUEST_VALIDATION_FAILED", "The request did not match the API contract.", details, 422)


def indicator_lookup(
    session: Session, dataset_version_id: int
) -> dict[int, dict[str, float | None]]:
    values: defaultdict[int, dict[str, float | None]] = defaultdict(dict)
    rows = session.scalars(
        select(IndicatorValue)
        .join(AdminArea, AdminArea.id == IndicatorValue.area_id)
        .where(AdminArea.dataset_version_id == dataset_version_id)
    ).all()
    for row in rows:
        values[row.area_id][row.indicator_code] = row.value
    return values


def load_area_records(
    session: Session, dataset_version_id: int
) -> list[dict[str, Any]]:
    values = indicator_lookup(session, dataset_version_id)
    rows = session.execute(
        select(AdminArea, func.ST_AsGeoJSON(AdminArea.geom, 6))
        .where(AdminArea.dataset_version_id == dataset_version_id)
        .order_by(AdminArea.code)
    ).all()
    return [
        {
            "id": area.id,
            "code": area.code,
            "name": area.name,
            "province": area.province,
            "population": area.population,
            "rice_area_ha": area.rice_area_ha,
            "data_quality": area.data_quality,
            "geometry": json.loads(geometry_json),
            "indicators": {
                code: values.get(area.id, {}).get(code) for code in INDICATORS
            },
        }
        for area, geometry_json in rows
    ]


def feature_collection(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": record["id"],
                "geometry": record["geometry"],
                "properties": {
                    key: value for key, value in record.items() if key != "geometry"
                },
            }
            for record in records
        ],
    }


def ranking_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": record["id"],
            "code": record["code"],
            "name": record["name"],
            "province": record["province"],
            "population": record["population"],
            "rank": record["rank"],
            "score": record["score"],
            "eligible": record["eligible"],
            "priority_band": record["priority_band"],
            "rice_area_ha": record["rice_area_ha"],
            "data_quality": record["data_quality"],
            "data_completeness": record["data_completeness"],
            "components": record["components"],
            "indicators": record["indicators"],
            "missing_indicators": record["missing_indicators"],
        }
        for record in records
        if record["eligible"]
    ]


def analysis_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [record for record in records if record["eligible"]]
    top_ten = eligible[:10]
    return {
        "total_areas": len(records),
        "eligible_areas": len(eligible),
        "excluded_areas": len(records) - len(eligible),
        "average_score": round(
            sum(record["score"] for record in eligible) / max(len(eligible), 1), 2
        ),
        "top_area": (
            {
                "name": eligible[0]["name"],
                "score": eligible[0]["score"],
                "province": eligible[0]["province"],
            }
            if eligible
            else None
        ),
        "top_10_rice_area_ha": round(
            sum(record["rice_area_ha"] for record in top_ten), 1
        ),
    }


def version_reference(version: DataVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "dataset_id": version.dataset_id,
        "dataset_name": version.dataset.name,
        "version_label": version.version_label,
        "status": version.status,
        "checksum_sha256": version.checksum_sha256,
        "record_count": version.record_count,
    }


def response_payload(run: AnalysisRun, records: list[dict[str, Any]]) -> dict[str, Any]:
    if run.dataset_version is None:
        raise HTTPException(status_code=409, detail="Analysis run has no dataset lineage")
    return {
        "run_id": run.id,
        "dataset_version": version_reference(run.dataset_version),
        "scenario_key": run.scenario_key,
        "weights": run.weights,
        "min_rice_area_ha": run.min_rice_area_ha,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "summary": analysis_summary(records),
        "ranking": ranking_rows(records),
        "geojson": feature_collection(records),
        "disclaimer": DEMO_DISCLAIMER,
    }


def load_persisted_run(
    session: Session, run_id: int
) -> tuple[AnalysisRun, list[dict[str, Any]]]:
    run = session.scalar(
        select(AnalysisRun)
        .options(
            selectinload(AnalysisRun.dataset_version).selectinload(DataVersion.dataset)
        )
        .where(AnalysisRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    if run.dataset_version_id is None:
        raise HTTPException(status_code=409, detail="Analysis run has no dataset version")

    base_areas = {
        record["id"]: record
        for record in load_area_records(session, run.dataset_version_id)
    }
    results = session.scalars(
        select(PriorityResult)
        .where(PriorityResult.run_id == run_id)
        .order_by(PriorityResult.eligible.desc(), PriorityResult.rank.asc().nulls_last())
    ).all()
    records: list[dict[str, Any]] = []
    for result in results:
        base = base_areas.get(result.area_id)
        if base is None:
            continue
        records.append(
            {
                **base,
                "score": result.score,
                "rank": result.rank,
                "eligible": result.eligible,
                "priority_band": result.priority_band,
                "components": result.components,
                "missing_indicators": result.missing_indicators,
                "data_completeness": round(
                    1 - len(result.missing_indicators) / len(INDICATORS), 3
                ),
            }
        )
    return run, records


def get_version_with_checks(session: Session, version_id: int) -> DataVersion:
    version = session.scalar(
        select(DataVersion)
        .options(
            selectinload(DataVersion.quality_checks), selectinload(DataVersion.dataset)
        )
        .where(DataVersion.id == version_id)
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Dataset version not found")
    return version


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "FAO Climate Geospatial Data & Decision Platform API",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    session.execute(text("SELECT 1"))
    ensure_bucket()
    dependencies = dependency_health()
    warnings = []
    if dependencies["worker"] != "ok":
        warnings.append("worker heartbeat unavailable")
    if ALLOW_INSECURE_DEV_FILE_SCAN:
        warnings.append("development file-scan bypass enabled")
    return {
        "status": "healthy_with_warnings" if warnings else "ok",
        "database": "ok",
        "object_storage": "ok",
        **dependencies,
        "auth_mode": AUTH_MODE,
        "file_scanner": "development_bypass" if ALLOW_INSECURE_DEV_FILE_SCAN else "approved_scanner_required",
        "warnings": warnings,
    }


@app.get("/api/catalog")
def catalog(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "apps.investment.use", "investment-prioritisation")
    indicator_sources = session.scalars(
        select(Dataset).order_by(Dataset.indicator_code)
    ).all()
    return {
        "indicators": INDICATORS,
        "scenarios": SCENARIOS,
        "datasets": [
            {
                "indicator_code": dataset.indicator_code,
                "title": dataset.title,
                "source_label": dataset.source_label,
                "methodology": dataset.methodology,
                "is_synthetic": dataset.is_synthetic,
                "last_updated": dataset.last_updated,
            }
            for dataset in indicator_sources
        ],
        "disclaimer": DEMO_DISCLAIMER,
        "method": {
            "name": "Transparent weighted linear combination",
            "formula": "score = Σ(normalised weight × oriented indicator) × quality adjustment",
            "missing_value_policy": (
                "Missing indicators receive a neutral value of 0.5 and are explicitly flagged."
            ),
        },
    }


@app.get("/api/data-catalog")
def data_catalog(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "data.catalog.enter")
    return catalog_payload(session)


@app.get("/api/data-versions/available")
def analysis_versions(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    assert_permission(principal, "apps.investment.use", "investment-prioritisation")
    return available_analysis_versions(session)


@app.post("/api/data-catalog/upload", deprecated=True)
async def upload_dataset_version(
    file: UploadFile = File(...),
    dataset_name: str = Form(""),
    description: str = Form(""),
    version_label: str = Form(...),
    dataset_id: int | None = Form(None),
    notes: str = Form(""),
    uploaded_by: str = Form("Mickey Lei"),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.upload_version")
    raise PlatformError(
        "LEGACY_CATALOG_READ_ONLY",
        "The legacy multipart catalog is read-only. Use the Data Hub direct-upload workflow.",
        410,
        {"replacement": "/api/data/v1/datasets"},
    )


@app.post("/api/data-versions/{version_id}/publish", deprecated=True)
def publish_dataset_version(
    version_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.publish")
    raise PlatformError(
        "LEGACY_CATALOG_READ_ONLY",
        "Legacy versions cannot be published through this endpoint. Use the governed Data Hub review and publish workflow.",
        410,
        {"replacement": "/api/data/v1/versions/{version_id}/publish"},
    )


@app.get("/api/data-versions/{version_id}/preview")
def preview_dataset_version(
    version_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "dataset.preview")
    get_version_with_checks(session, version_id)
    return feature_collection(load_area_records(session, version_id))


@app.get("/api/data-versions/{version_id}/download")
def download_dataset_version(
    version_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> Response:
    assert_permission(principal, "dataset.download")
    version = get_version_with_checks(session, version_id)
    try:
        payload = get_bytes(version.object_key)
    except Exception as error:
        raise HTTPException(status_code=503, detail="Stored source file is unavailable") from error
    filename = version.source_filename.replace('"', "")
    return Response(
        content=payload,
        media_type=version.media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/areas")
def areas(
    dataset_version_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "apps.investment.use", "investment-prioritisation")
    get_version_with_checks(session, dataset_version_id)
    return feature_collection(load_area_records(session, dataset_version_id))


@app.get("/api/scenarios")
def scenarios(principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    assert_permission(principal, "apps.investment.use", "investment-prioritisation")
    return SCENARIOS


@app.post("/api/analysis/run")
def run_analysis(
    request: AnalysisRequest,
    http_request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.create", "investment-prioritisation")
    scenario = SCENARIOS.get(request.scenario_key)
    if scenario is None:
        raise HTTPException(status_code=400, detail="Unknown scenario")

    version = get_version_with_checks(session, request.dataset_version_id)
    if version.status != "published":
        raise HTTPException(
            status_code=409, detail="Only a published dataset version can be analysed"
        )
    records = load_area_records(session, version.id)
    if not records:
        raise HTTPException(status_code=409, detail="Dataset version has no analysis records")

    weights = normalise_weights(request.weights or scenario["weights"])
    records = calculate_priorities(records, weights, request.min_rice_area_ha)
    run = AnalysisRun(
        dataset_version_id=version.id,
        scenario_key=request.scenario_key,
        weights=weights,
        min_rice_area_ha=request.min_rice_area_ha,
        dataset_version=version,
    )
    session.add(run)
    session.flush()

    for record in records:
        session.add(
            PriorityResult(
                run_id=run.id,
                area_id=record["id"],
                score=record["score"],
                rank=record["rank"],
                eligible=record["eligible"],
                priority_band=record["priority_band"],
                components=record["components"],
                missing_indicators=record["missing_indicators"],
            )
        )
    session.commit()
    session.refresh(run)
    return response_payload(run, records)


@app.post("/api/analysis/preview")
def preview_analysis(
    request: AnalysisRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Calculate the initial map without creating an analysis run."""

    assert_permission(principal, "apps.investment.use", "investment-prioritisation")
    scenario = SCENARIOS.get(request.scenario_key)
    if scenario is None:
        raise HTTPException(status_code=400, detail="Unknown scenario")
    version = get_version_with_checks(session, request.dataset_version_id)
    if version.status != "published":
        raise HTTPException(status_code=409, detail="Only a published dataset version can be previewed")
    weights = normalise_weights(request.weights or scenario["weights"])
    records = calculate_priorities(load_area_records(session, version.id), weights, request.min_rice_area_ha)
    return {
        "run_id": 0,
        "persisted": False,
        "dataset_version": version_reference(version),
        "scenario_key": request.scenario_key,
        "weights": weights,
        "min_rice_area_ha": request.min_rice_area_ha,
        "created_at": None,
        "summary": analysis_summary(records),
        "ranking": ranking_rows(records),
        "geojson": feature_collection(records),
        "disclaimer": DEMO_DISCLAIMER,
    }


@app.get("/api/analysis/{run_id}")
def get_analysis(
    run_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    assert_permission(principal, "investment.run.view", "investment-prioritisation")
    run, records = load_persisted_run(session, run_id)
    return response_payload(run, records)


@app.get("/api/analysis/{run_id}/ranking")
def get_ranking(
    run_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    assert_permission(principal, "investment.run.view", "investment-prioritisation")
    _, records = load_persisted_run(session, run_id)
    return ranking_rows(records)


@app.get("/api/analysis/{run_id}/export.csv")
def export_csv(
    run_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> Response:
    assert_permission(principal, "investment.run.export", "investment-prioritisation")
    run, records = load_persisted_run(session, run_id)
    buffer = io.StringIO()
    fieldnames = [
        "dataset_version_id",
        "dataset_version",
        "rank",
        "code",
        "name",
        "province",
        "score",
        "priority_band",
        "eligible",
        "rice_area_ha",
        "population",
        "data_completeness",
        *INDICATORS.keys(),
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "dataset_version_id": run.dataset_version_id,
                "dataset_version": run.dataset_version.version_label,
                "rank": record["rank"],
                "code": record["code"],
                "name": record["name"],
                "province": record["province"],
                "score": record["score"],
                "priority_band": record["priority_band"],
                "eligible": record["eligible"],
                "rice_area_ha": record["rice_area_ha"],
                "population": record["population"],
                "data_completeness": record["data_completeness"],
                **record["indicators"],
            }
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="rice-priority-run-{run_id}.csv"'
        },
    )


@app.get("/api/analysis/{run_id}/export.geojson")
def export_geojson(
    run_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> Response:
    assert_permission(principal, "investment.run.export", "investment-prioritisation")
    run, records = load_persisted_run(session, run_id)
    collection = feature_collection(records)
    collection["metadata"] = {
        "analysis_run_id": run.id,
        "dataset_version": version_reference(run.dataset_version),
        "scenario_key": run.scenario_key,
        "weights": run.weights,
    }
    return Response(
        content=json.dumps(collection),
        media_type="application/geo+json",
        headers={
            "Content-Disposition": f'attachment; filename="rice-priority-run-{run_id}.geojson"'
        },
    )
