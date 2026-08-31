from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from geoalchemy2.shape import from_shape
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.ingestion import ParsedUpload
from app.models import (
    AdminArea,
    DataCatalogItem,
    DataQualityCheck,
    DataVersion,
    IndicatorValue,
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "dataset"


def unique_slug(session: Session, name: str) -> str:
    base = slugify(name)
    candidate = base
    suffix = 2
    while session.scalar(select(DataCatalogItem.id).where(DataCatalogItem.slug == candidate)):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def quality_summary(version: DataVersion) -> dict[str, int]:
    summary = {"passed": 0, "warning": 0, "failed": 0}
    for check in version.quality_checks:
        summary[check.status] = summary.get(check.status, 0) + 1
    return summary


def serialise_quality_check(check: DataQualityCheck) -> dict[str, Any]:
    return {
        "id": check.id,
        "check_code": check.check_code,
        "check_name": check.check_name,
        "status": check.status,
        "severity": check.severity,
        "details": check.details,
        "affected_count": check.affected_count,
    }


def serialise_version(version: DataVersion, include_checks: bool = True) -> dict[str, Any]:
    return {
        "id": version.id,
        "dataset_id": version.dataset_id,
        "version_label": version.version_label,
        "status": version.status,
        "is_current": version.is_current,
        "source_filename": version.source_filename,
        "file_size": version.file_size,
        "media_type": version.media_type,
        "checksum_sha256": version.checksum_sha256,
        "record_count": version.record_count,
        "schema_summary": version.schema_summary,
        "notes": version.notes,
        "uploaded_by": version.uploaded_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "published_at": (
            version.published_at.isoformat() if version.published_at else None
        ),
        "quality_summary": quality_summary(version),
        "quality_checks": (
            [serialise_quality_check(check) for check in version.quality_checks]
            if include_checks
            else []
        ),
        "download_url": f"/api/data-versions/{version.id}/download",
        "preview_url": f"/api/data-versions/{version.id}/preview",
        "analysis_ready": version.status == "published" and version.record_count > 0,
    }


def serialise_dataset(dataset: DataCatalogItem) -> dict[str, Any]:
    versions = sorted(dataset.versions, key=lambda version: version.id, reverse=True)
    return {
        "id": dataset.id,
        "slug": dataset.slug,
        "name": dataset.name,
        "description": dataset.description,
        "data_kind": dataset.data_kind,
        "owner": dataset.owner,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "current_version_id": next(
            (version.id for version in versions if version.is_current), None
        ),
        "versions": [serialise_version(version) for version in versions],
    }


def catalog_payload(session: Session) -> dict[str, Any]:
    datasets = session.scalars(
        select(DataCatalogItem)
        .options(
            selectinload(DataCatalogItem.versions).selectinload(
                DataVersion.quality_checks
            )
        )
        .order_by(DataCatalogItem.created_at.desc(), DataCatalogItem.id.desc())
    ).all()
    all_versions = [version for dataset in datasets for version in dataset.versions]
    return {
        "datasets": [serialise_dataset(dataset) for dataset in datasets],
        "summary": {
            "datasets": len(datasets),
            "versions": len(all_versions),
            "published_versions": sum(
                1 for version in all_versions if version.status == "published"
            ),
            "stored_bytes": sum(version.file_size for version in all_versions),
            "quality_warnings": sum(
                quality_summary(version).get("warning", 0) for version in all_versions
            ),
            "failed_versions": sum(
                1
                for version in all_versions
                if quality_summary(version).get("failed", 0) > 0
            ),
        },
    }


def available_analysis_versions(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(DataVersion, DataCatalogItem)
        .join(DataCatalogItem, DataCatalogItem.id == DataVersion.dataset_id)
        .options(selectinload(DataVersion.quality_checks))
        .where(DataVersion.status == "published", DataVersion.record_count > 0)
        .order_by(DataVersion.is_current.desc(), DataVersion.id.desc())
    ).all()
    return [
        {
            **serialise_version(version, include_checks=False),
            "dataset_name": dataset.name,
            "dataset_description": dataset.description,
            "display_name": f"{dataset.name} · {version.version_label}",
        }
        for version, dataset in rows
    ]


def import_parsed_records(
    session: Session, version: DataVersion, parsed: ParsedUpload
) -> None:
    for record in parsed.records:
        area = AdminArea(
            dataset_version_id=version.id,
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


def publish_version(session: Session, version: DataVersion) -> None:
    if version.status not in {"validated", "published"}:
        raise ValueError("Only a validated version can be published")
    if any(check.status == "failed" for check in version.quality_checks):
        raise ValueError("Resolve failed quality checks before publishing")
    if version.record_count <= 0:
        raise ValueError("A published analysis version must contain spatial records")

    session.query(DataVersion).filter(
        DataVersion.dataset_id == version.dataset_id,
        DataVersion.id != version.id,
    ).update({DataVersion.is_current: False})
    version.status = "published"
    version.is_current = True
    version.published_at = datetime.now(timezone.utc)


def count_version_areas(session: Session, version_id: int) -> int:
    return (
        session.scalar(
            select(func.count(AdminArea.id)).where(
                AdminArea.dataset_version_id == version_id
            )
        )
        or 0
    )

