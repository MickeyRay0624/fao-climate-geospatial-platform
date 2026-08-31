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
from app.platform_models import (
    CatalogAsset,
    CatalogDataset,
    CatalogDatasetVersion,
    LegacyIdMapping,
    QualityRun,
    User,
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
    """Adapt the authoritative platform catalog to the legacy investment shape.

    Only deterministically mapped versions can be consumed by the integer-ID
    investment read model. New catalog records remain visible in the Data Hub,
    while this adapter keeps the existing module stable without dual writes.
    """

    dataset_mappings = {
        mapping.new_id: int(mapping.legacy_id)
        for mapping in session.scalars(
            select(LegacyIdMapping).where(
                LegacyIdMapping.entity_type == "data_catalog_items"
            )
        ).all()
        if mapping.legacy_id.isdigit()
    }
    version_mappings = {
        mapping.new_id: int(mapping.legacy_id)
        for mapping in session.scalars(
            select(LegacyIdMapping).where(
                LegacyIdMapping.entity_type == "data_versions"
            )
        ).all()
        if mapping.legacy_id.isdigit()
    }
    platform_datasets = session.scalars(
        select(CatalogDataset)
        .where(
            CatalogDataset.id.in_(list(dataset_mappings)),
            CatalogDataset.lifecycle_status != "ARCHIVED",
        )
        .order_by(CatalogDataset.created_at.desc())
    ).all()
    datasets: list[dict[str, Any]] = []
    all_versions: list[dict[str, Any]] = []
    state_map = {
        "DRAFT": "draft",
        "UPLOADING": "draft",
        "PROCESSING": "draft",
        "VALIDATION_FAILED": "draft",
        "VALIDATED": "validated",
        "IN_REVIEW": "validated",
        "CHANGES_REQUESTED": "draft",
        "APPROVED": "validated",
        "PUBLISHED": "published",
        "DEPRECATED": "archived",
        "ARCHIVED": "archived",
    }
    for platform_dataset in platform_datasets:
        owner = session.get(User, platform_dataset.owner_user_id)
        version_rows: list[dict[str, Any]] = []
        platform_versions = session.scalars(
            select(CatalogDatasetVersion)
            .where(
                CatalogDatasetVersion.dataset_id == platform_dataset.id,
                CatalogDatasetVersion.id.in_(list(version_mappings)),
            )
            .order_by(CatalogDatasetVersion.created_at.desc())
        ).all()
        for platform_version in platform_versions:
            legacy_id = version_mappings[platform_version.id]
            legacy_version = session.scalar(
                select(DataVersion)
                .options(selectinload(DataVersion.quality_checks))
                .where(DataVersion.id == legacy_id)
            )
            if legacy_version is None:
                continue
            asset = session.scalar(
                select(CatalogAsset)
                .where(
                    CatalogAsset.dataset_version_id == platform_version.id,
                    CatalogAsset.role == "source",
                )
                .order_by(CatalogAsset.created_at)
                .limit(1)
            )
            quality = session.scalar(
                select(QualityRun)
                .where(QualityRun.dataset_version_id == platform_version.id)
                .order_by(QualityRun.completed_at.desc().nulls_last())
                .limit(1)
            )
            summary = quality.summary_json if quality else quality_summary(legacy_version)
            status = state_map.get(platform_version.state, "draft")
            payload = {
                **serialise_version(legacy_version),
                "version_label": platform_version.version_label,
                "status": status,
                "is_current": platform_dataset.current_published_version_id == platform_version.id,
                "source_filename": asset.filename if asset else legacy_version.source_filename,
                "file_size": asset.size_bytes if asset else legacy_version.file_size,
                "media_type": asset.media_type if asset else legacy_version.media_type,
                "checksum_sha256": asset.sha256 if asset else legacy_version.checksum_sha256,
                "notes": platform_version.change_summary,
                "uploaded_by": owner.display_name if owner else legacy_version.uploaded_by,
                "quality_summary": {
                    "passed": int(summary.get("passed", 0)),
                    "warning": int(summary.get("warning", summary.get("warnings", 0))),
                    "failed": int(summary.get("failed", summary.get("blocking", 0))),
                },
                "analysis_ready": status == "published" and legacy_version.record_count > 0,
            }
            version_rows.append(payload)
            all_versions.append(payload)
        datasets.append(
            {
                "id": dataset_mappings[platform_dataset.id],
                "slug": platform_dataset.slug,
                "name": platform_dataset.title,
                "description": platform_dataset.abstract,
                "data_kind": platform_dataset.data_kind,
                "owner": owner.display_name if owner else "Legacy attribution",
                "created_at": platform_dataset.created_at.isoformat() if platform_dataset.created_at else None,
                "current_version_id": next(
                    (version["id"] for version in version_rows if version["is_current"]),
                    None,
                ),
                "versions": version_rows,
            }
        )
    return {
        "datasets": datasets,
        "summary": {
            "datasets": len(datasets),
            "versions": len(all_versions),
            "published_versions": sum(
                1 for version in all_versions if version["status"] == "published"
            ),
            "stored_bytes": sum(version["file_size"] for version in all_versions),
            "quality_warnings": sum(
                version["quality_summary"].get("warning", 0) for version in all_versions
            ),
            "failed_versions": sum(
                1
                for version in all_versions
                if version["quality_summary"].get("failed", 0) > 0
            ),
        },
    }


def available_analysis_versions(session: Session) -> list[dict[str, Any]]:
    catalog = catalog_payload(session)
    rows = [
        {
            **version,
            "quality_checks": [],
            "dataset_name": dataset["name"],
            "dataset_description": dataset["description"],
            "display_name": f"{dataset['name']} · {version['version_label']}",
        }
        for dataset in catalog["datasets"]
        for version in dataset["versions"]
        if version["status"] == "published" and version["record_count"] > 0
    ]
    return sorted(rows, key=lambda item: (not item["is_current"], -item["id"]))


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
