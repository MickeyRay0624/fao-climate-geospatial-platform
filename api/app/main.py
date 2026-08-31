from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.analysis import calculate_priorities, normalise_weights
from app.catalog import INDICATORS, SCENARIOS
from app.config import CORS_ORIGINS, DEMO_DISCLAIMER, MAX_UPLOAD_BYTES
from app.data_management import (
    available_analysis_versions,
    catalog_payload,
    import_parsed_records,
    publish_version,
    serialise_dataset,
    serialise_version,
    unique_slug,
)
from app.database import get_session
from app.ingestion import parse_upload, supported_media_type
from app.migrations import ensure_schema
from app.models import (
    AdminArea,
    AnalysisRun,
    DataCatalogItem,
    DataQualityCheck,
    DataVersion,
    Dataset,
    IndicatorValue,
    PriorityResult,
)
from app.object_store import ensure_bucket, get_bytes, put_bytes, remove_object
from app.schemas import AnalysisRequest


ensure_schema()

app = FastAPI(
    title="Cambodia Spatial Data & Rice Prioritisation API",
    version="0.2.0",
    description=(
        "Versioned spatial data management and transparent multi-criteria analysis "
        "for a local demonstrator."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        "name": "Cambodia Spatial Data & Rice Prioritisation API",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    ensure_bucket()
    return {"status": "ok", "database": "ok", "object_storage": "ok"}


@app.get("/api/catalog")
def catalog(session: Session = Depends(get_session)) -> dict[str, Any]:
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
def data_catalog(session: Session = Depends(get_session)) -> dict[str, Any]:
    return catalog_payload(session)


@app.get("/api/data-versions/available")
def analysis_versions(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return available_analysis_versions(session)


@app.post("/api/data-catalog/upload")
async def upload_dataset_version(
    file: UploadFile = File(...),
    dataset_name: str = Form(""),
    description: str = Form(""),
    version_label: str = Form(...),
    dataset_id: int | None = Form(None),
    notes: str = Form(""),
    uploaded_by: str = Form("Mickey Lei"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    safe_filename = Path(file.filename or "upload").name
    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 25 MB MVP limit")
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    clean_version = version_label.strip()
    if not clean_version:
        raise HTTPException(status_code=400, detail="Version label is required")

    if dataset_id is not None:
        dataset = session.get(DataCatalogItem, dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
    else:
        clean_name = dataset_name.strip()
        if not clean_name:
            raise HTTPException(
                status_code=400, detail="Dataset name is required for a new dataset"
            )
        dataset = DataCatalogItem(
            slug=unique_slug(session, clean_name),
            name=clean_name,
            description=description.strip(),
            data_kind="analysis_bundle",
            owner="DSS team",
        )
        session.add(dataset)
        session.flush()

    duplicate = session.scalar(
        select(DataVersion.id).where(
            DataVersion.dataset_id == dataset.id,
            DataVersion.version_label == clean_version,
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=409, detail="This dataset already has that version label"
        )

    parsed = parse_upload(safe_filename, payload)
    checksum = hashlib.sha256(payload).hexdigest()
    version = DataVersion(
        dataset_id=dataset.id,
        version_label=clean_version,
        status="draft" if parsed.has_failures else "validated",
        is_current=False,
        source_filename=safe_filename,
        object_key="pending",
        checksum_sha256=checksum,
        file_size=len(payload),
        media_type=file.content_type or supported_media_type(safe_filename),
        record_count=0 if parsed.has_failures else len(parsed.records),
        schema_summary=parsed.schema_summary,
        notes=notes.strip(),
        uploaded_by=uploaded_by.strip() or "DSS team member",
    )
    session.add(version)
    session.flush()
    object_key = f"datasets/{dataset.id}/versions/{version.id}/{safe_filename}"

    try:
        put_bytes(object_key, payload, version.media_type)
        version.object_key = object_key
        for check in parsed.checks:
            version.quality_checks.append(
                DataQualityCheck(
                    check_code=check.code,
                    check_name=check.name,
                    status=check.status,
                    severity=check.severity,
                    details=check.details,
                    affected_count=check.affected_count,
                )
            )
        if not parsed.has_failures:
            import_parsed_records(session, version, parsed)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        remove_object(object_key)
        raise HTTPException(
            status_code=409, detail="The uploaded version contains conflicting records"
        ) from error
    except HTTPException:
        raise
    except Exception as error:
        session.rollback()
        remove_object(object_key)
        raise HTTPException(
            status_code=503, detail=f"Upload could not be stored: {error}"
        ) from error

    dataset = session.scalar(
        select(DataCatalogItem)
        .options(
            selectinload(DataCatalogItem.versions).selectinload(
                DataVersion.quality_checks
            )
        )
        .where(DataCatalogItem.id == dataset.id)
    )
    if dataset is None:
        raise HTTPException(status_code=500, detail="Dataset could not be reloaded")
    return {"dataset": serialise_dataset(dataset), "uploaded_version_id": version.id}


@app.post("/api/data-versions/{version_id}/publish")
def publish_dataset_version(
    version_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    version = get_version_with_checks(session, version_id)
    try:
        publish_version(session, version)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    session.commit()
    session.refresh(version)
    return serialise_version(version)


@app.get("/api/data-versions/{version_id}/preview")
def preview_dataset_version(
    version_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    get_version_with_checks(session, version_id)
    return feature_collection(load_area_records(session, version_id))


@app.get("/api/data-versions/{version_id}/download")
def download_dataset_version(
    version_id: int, session: Session = Depends(get_session)
) -> Response:
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
    dataset_version_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    get_version_with_checks(session, dataset_version_id)
    return feature_collection(load_area_records(session, dataset_version_id))


@app.get("/api/scenarios")
def scenarios() -> dict[str, Any]:
    return SCENARIOS


@app.post("/api/analysis/run")
def run_analysis(
    request: AnalysisRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
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


@app.get("/api/analysis/{run_id}")
def get_analysis(run_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    run, records = load_persisted_run(session, run_id)
    return response_payload(run, records)


@app.get("/api/analysis/{run_id}/ranking")
def get_ranking(
    run_id: int, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    _, records = load_persisted_run(session, run_id)
    return ranking_rows(records)


@app.get("/api/analysis/{run_id}/export.csv")
def export_csv(run_id: int, session: Session = Depends(get_session)) -> Response:
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
def export_geojson(run_id: int, session: Session = Depends(get_session)) -> Response:
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

