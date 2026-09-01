from __future__ import annotations

import argparse
import csv
import io
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_service import record_event
from app.catalog import INDICATORS
from app.config import DEMO_DISCLAIMER
from app.database import SessionLocal
from app.datahub.validators import ValidationResult, validate_file
from app.investment.canonical import canonical_json, checksum_json
from app.investment.constants import INDICATOR_CODES, LEGACY_METHOD_SPEC
from app.investment.engine import normalise_weights, score_priority_areas
from app.investment.seed import investment_id, seed_investment_governance
from app.investment.service import (
    canonical_input_set,
    create_run_inputs,
    materialise_results,
    put_immutable_verified,
    register_output,
    validate_input_set,
)
from app.models import (
    AdminArea,
    AnalysisRun as LegacyAnalysisRun,
    DataVersion,
    IndicatorValue,
    PriorityResult as LegacyPriorityResult,
)
from app.object_store import get_bytes
from app.platform_models import (
    CatalogAsset,
    CatalogDataset,
    CatalogDatasetVersion,
    InvestmentAnalysisInputMember,
    InvestmentAnalysisInputSet,
    InvestmentAnalysisRun,
    InvestmentAnalysisRunInput,
    InvestmentMethodVersion,
    InvestmentPriorityResult,
    InvestmentScenario,
    LegacyIdMapping,
    LineageEdge,
    LineageProcess,
    MetadataRecord,
    QualityIssue,
    QualityProfile,
    QualityRun,
    Representation,
    User,
    Workspace,
)


LEGACY_SOURCE_KEY = "datasets/1/versions/1/cambodia-rice-priority-synthetic-v1.geojson"
LEGACY_SOURCE_SHA256 = "c30bb60f2f45ae9374578e25760a46f00257f45766bf5640c67d1cd23a34df9b"
LEGACY_SOURCE_SIZE = 54213
HISTORICAL_CODE_REF = "git:71c4bd152b68359a7c84824ab673ec089f60b547:phase1-execution"
MIGRATION_VERSION = "investment-native-phase-2a/1.0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mapping(
    session: Session,
    entity_type: str,
    legacy_id: int,
    new_id: uuid.UUID,
    **metadata: Any,
) -> LegacyIdMapping:
    item = session.scalar(
        select(LegacyIdMapping).where(
            LegacyIdMapping.entity_type == entity_type,
            LegacyIdMapping.legacy_id == str(legacy_id),
        )
    )
    if item is None:
        item = LegacyIdMapping(
            id=investment_id("legacy-mapping", f"{entity_type}:{legacy_id}"),
            entity_type=entity_type,
            legacy_id=str(legacy_id),
            new_id=new_id,
            metadata_json={"migration_version": MIGRATION_VERSION, **metadata},
        )
        session.add(item)
    elif item.new_id != new_id:
        raise RuntimeError(
            f"LEGACY_MAPPING_CONFLICT:{entity_type}:{legacy_id}:{item.new_id}:{new_id}"
        )
    return item


def _context(session: Session) -> dict[str, Any]:
    seeded = seed_investment_governance(session)
    workspace = seeded["workspace"]
    legacy_user = session.scalar(select(User).where(User.external_subject == "mickey-legacy"))
    legacy_version = session.get(DataVersion, 1)
    catalog_version = session.scalar(
        select(CatalogDatasetVersion)
        .join(CatalogDataset, CatalogDataset.id == CatalogDatasetVersion.dataset_id)
        .where(
            CatalogDataset.workspace_id == workspace.id,
            CatalogDataset.slug == "cambodia-rice-priority-synthetic",
            CatalogDatasetVersion.version_label == "1.0.0",
        )
    )
    if not legacy_user or not legacy_version or not catalog_version:
        raise RuntimeError("LEGACY_MIGRATION_CONTEXT_UNAVAILABLE")
    if legacy_version.object_key != LEGACY_SOURCE_KEY:
        raise RuntimeError("LEGACY_SOURCE_LOCATOR_CHANGED")
    payload = get_bytes(legacy_version.object_key)
    if (
        len(payload) != LEGACY_SOURCE_SIZE
        or legacy_version.file_size != LEGACY_SOURCE_SIZE
        or legacy_version.checksum_sha256 != LEGACY_SOURCE_SHA256
        or put_immutable_verified(legacy_version.object_key, payload, legacy_version.media_type)
        != LEGACY_SOURCE_SHA256
    ):
        raise RuntimeError("LEGACY_SOURCE_EVIDENCE_CHANGED")
    return {
        **seeded,
        "workspace": workspace,
        "legacy_user": legacy_user,
        "legacy_version": legacy_version,
        "catalog_version": catalog_version,
    }


def _area_records(session: Session) -> list[dict[str, Any]]:
    value_rows = session.scalars(
        select(IndicatorValue)
        .join(AdminArea, AdminArea.id == IndicatorValue.area_id)
        .where(AdminArea.dataset_version_id == 1)
        .order_by(IndicatorValue.area_id, IndicatorValue.indicator_code)
    ).all()
    values: defaultdict[int, dict[str, float | None]] = defaultdict(dict)
    flags: defaultdict[int, dict[str, str]] = defaultdict(dict)
    for value in value_rows:
        values[value.area_id][value.indicator_code] = value.value
        flags[value.area_id][value.indicator_code] = value.quality_flag
    rows = session.execute(
        select(AdminArea, func.ST_AsGeoJSON(AdminArea.geom, 6))
        .where(AdminArea.dataset_version_id == 1)
        .order_by(AdminArea.code)
    ).all()
    return [
        {
            "legacy_area_id": area.id,
            "code": area.code,
            "name": area.name,
            "admin_level": "commune",
            "province": area.province,
            "population": area.population,
            "rice_area_ha": area.rice_area_ha,
            "data_quality": area.data_quality,
            "geometry": json.loads(geometry_json),
            "indicators": {
                code: values[area.id].get(code) for code in INDICATOR_CODES
            },
            "source_quality_flags": {
                "synthetic": True,
                "legacy_area_id": area.id,
                "indicator_flags": flags[area.id],
            },
        }
        for area, geometry_json in rows
    ]


def _boundary_payload(areas: list[dict[str, Any]]) -> bytes:
    document = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "metadata": {
            "synthetic": True,
            "operational_use": False,
            "derived_from_legacy_bundle": True,
            "disclaimer": DEMO_DISCLAIMER,
        },
        "features": [
            {
                "type": "Feature",
                "id": area["code"],
                "geometry": area["geometry"],
                "properties": {
                    "area_code": area["code"],
                    "area_name": area["name"],
                    "admin_level": area["admin_level"],
                    "province": area["province"],
                    "population": area["population"],
                    "rice_area_ha": area["rice_area_ha"],
                    "data_quality": area["data_quality"],
                },
            }
            for area in areas
        ],
    }
    return canonical_json(document).encode("utf-8")


def _indicator_payload(areas: list[dict[str, Any]], indicator_code: str) -> bytes:
    buffer = io.StringIO(newline="")
    fields = [
        "area_code",
        "value",
        "indicator_code",
        "unit",
        "direction",
        "time_start",
        "time_end",
        "quality_flag",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for area in areas:
        value = area["indicators"][indicator_code]
        writer.writerow(
            {
                "area_code": area["code"],
                "value": "" if value is None else value,
                "indicator_code": indicator_code,
                "unit": INDICATORS[indicator_code]["unit"],
                "direction": "higher_is_priority",
                "time_start": "2026-08-28",
                "time_end": "2026-08-28",
                "quality_flag": area["source_quality_flags"]["indicator_flags"].get(
                    indicator_code, "unknown/not_recorded"
                ),
            }
        )
    return buffer.getvalue().encode("utf-8")


def _quality_profile(session: Session, profile_key: str) -> QualityProfile:
    key, version = profile_key.split("@", 1)
    profile = session.scalar(
        select(QualityProfile).where(
            QualityProfile.profile_key == key,
            QualityProfile.profile_version == version,
        )
    )
    if profile is None:
        raise RuntimeError(f"QUALITY_PROFILE_NOT_FOUND:{profile_key}")
    return profile


def _register_layer(
    session: Session,
    *,
    workspace: Workspace,
    creator: User,
    source_version: CatalogDatasetVersion,
    layer_key: str,
    title: str,
    abstract: str,
    data_kind: str,
    profile_key: str,
    filename: str,
    media_type: str,
    representation_type: str,
    payload: bytes,
    validation: ValidationResult,
) -> tuple[CatalogDatasetVersion, Representation]:
    if validation.has_blocking:
        raise RuntimeError(
            f"LAYER_VALIDATION_FAILED:{layer_key}:"
            + ",".join(issue.code for issue in validation.issues if issue.severity == "BLOCKING")
        )
    dataset_id = investment_id("decomposed-dataset", f"{workspace.id}:{layer_key}")
    version_id = investment_id("decomposed-version", f"{dataset_id}:1.0.0")
    asset_id = investment_id("decomposed-asset", str(version_id))
    representation_id = investment_id("decomposed-representation", str(version_id))
    object_key = (
        f"catalog/{workspace.id}/datasets/{dataset_id}/versions/{version_id}/source/{filename}"
    )
    digest = put_immutable_verified(object_key, payload, media_type)

    dataset = session.get(CatalogDataset, dataset_id)
    version = session.get(CatalogDatasetVersion, version_id)
    representation = session.get(Representation, representation_id)
    if version is not None:
        asset = session.get(CatalogAsset, asset_id)
        if (
            dataset is None
            or representation is None
            or asset is None
            or version.state != "PUBLISHED"
            or asset.object_key != object_key
            or asset.sha256 != digest
            or asset.size_bytes != len(payload)
            or representation.locator != object_key
        ):
            raise RuntimeError(f"DECOMPOSED_LAYER_EVIDENCE_CONFLICT:{layer_key}")
        return version, representation

    if dataset is None:
        dataset = CatalogDataset(
            id=dataset_id,
            workspace_id=workspace.id,
            slug=f"synthetic-{layer_key}",
            title=title,
            abstract=abstract,
            data_kind=data_kind,
            owner_user_id=creator.id,
            visibility="WORKSPACE",
            classification="FAO_INTERNAL",
            lifecycle_status="ACTIVE",
            licence_code="DEMO-ONLY",
            created_by=creator.id,
            updated_by=creator.id,
        )
        session.add(dataset)
        session.flush()
    version = CatalogDatasetVersion(
        id=version_id,
        dataset_id=dataset.id,
        version_label="1.0.0",
        state="DRAFT",
        profile_key=profile_key,
        change_summary="Deterministic Phase 2A decomposition of the preserved legacy bundle.",
        metadata_snapshot={
            "record_count": validation.record_count,
            "synthetic": True,
            "operational_use": False,
            "derived_from_dataset_version_id": str(source_version.id),
            "migration_version": MIGRATION_VERSION,
            "disclaimer": DEMO_DISCLAIMER,
        },
        created_by=creator.id,
        approved_by=creator.id,
        published_by=creator.id,
    )
    session.add(version)
    session.flush()
    session.add(
        CatalogAsset(
            id=asset_id,
            dataset_version_id=version.id,
            role="source",
            filename=filename,
            object_key=object_key,
            media_type=media_type,
            size_bytes=len(payload),
            sha256=digest,
            scan_status="CLEAN",
            storage_class="STANDARD",
        )
    )
    representation = Representation(
        id=representation_id,
        dataset_version_id=version.id,
        representation_type=representation_type,
        locator=object_key,
        status="READY",
        crs=validation.crs,
        geometry_type=validation.geometry_type,
        bbox_json=validation.bbox,
        schema_json=validation.schema,
        statistics_json={"record_count": validation.record_count},
        preview_json=validation.preview,
    )
    session.add(representation)
    session.add(
        MetadataRecord(
            id=investment_id("decomposed-metadata", str(version.id)),
            dataset_version_id=version.id,
            title=title,
            abstract=abstract,
            purpose="Provide a governed exact-version input for the native investment module.",
            producer="FAO DSS demonstration team (deterministic migration)",
            provenance=(
                f"Byte-stable decomposition of catalog version {source_version.id}; "
                "no external or operational source was introduced."
            ),
            licence_code="DEMO-ONLY",
            use_limitation=DEMO_DISCLAIMER,
            crs=validation.crs,
            methodology="Direct field-preserving decomposition from the immutable synthetic legacy bundle.",
            quality_statement="Validated with the Phase 2A profile; synthetic and illustrative only.",
            keywords=["synthetic", "migration", "investment prioritisation", layer_key],
            sensitive_data_declaration="No personal data; synthetic values and geometries.",
        )
    )
    quality_run = QualityRun(
        id=investment_id("decomposed-quality-run", str(version.id)),
        dataset_version_id=version.id,
        quality_profile_id=_quality_profile(session, profile_key).id,
        engine_version="platform-validator/phase-2a",
        status="WARNING" if validation.issues else "PASSED",
        started_at=_utcnow(),
        completed_at=_utcnow(),
        summary_json={
            "record_count": validation.record_count,
            "warning": sum(issue.severity == "WARNING" for issue in validation.issues),
            "blocking": 0,
        },
    )
    session.add(quality_run)
    session.flush()
    for ordinal, issue in enumerate(validation.issues):
        session.add(
            QualityIssue(
                id=investment_id(
                    "decomposed-quality-issue", f"{quality_run.id}:{ordinal}:{issue.code}"
                ),
                quality_run_id=quality_run.id,
                code=issue.code,
                name=issue.name,
                severity=issue.severity,
                affected_count=issue.affected_count,
                details_json={"message": issue.message, **issue.details},
            )
        )
    session.flush()
    published_at = _utcnow()
    version.state = "PUBLISHED"
    version.approved_at = published_at
    version.published_at = published_at
    dataset.current_published_version_id = version.id
    session.flush()

    process = LineageProcess(
        id=investment_id("decomposed-lineage-process", layer_key),
        workspace_id=workspace.id,
        process_type="transformation",
        module_key="investment-prioritisation",
        external_run_type="legacy_input_decomposition",
        external_run_id=layer_key,
        method_identifier="field-preserving-bundle-decomposition",
        method_version="1.0",
        code_ref=HISTORICAL_CODE_REF,
        parameters_json={
            "source_version_id": str(source_version.id),
            "output_sha256": digest,
            "migration_version": MIGRATION_VERSION,
        },
        status="SUCCEEDED",
        completed_at=published_at,
    )
    session.add(process)
    session.flush()
    session.add_all(
        [
            LineageEdge(
                id=investment_id("decomposed-lineage-edge", f"{layer_key}:input"),
                process_id=process.id,
                direction="INPUT",
                dataset_version_id=source_version.id,
                role="legacy_priority_bundle",
                ordinal=0,
            ),
            LineageEdge(
                id=investment_id("decomposed-lineage-edge", f"{layer_key}:output"),
                process_id=process.id,
                direction="OUTPUT",
                dataset_version_id=version.id,
                role=layer_key,
                ordinal=0,
            ),
        ]
    )
    return version, representation


def _ensure_separate_layers(
    session: Session, context: dict[str, Any], areas: list[dict[str, Any]]
) -> InvestmentAnalysisInputSet:
    workspace: Workspace = context["workspace"]
    creator: User = context["legacy_user"]
    source_version: CatalogDatasetVersion = context["catalog_version"]
    boundary_payload = _boundary_payload(areas)
    boundary_validation = validate_file(
        "administrative-boundary@1.0",
        "synthetic-commune-boundaries.geojson",
        boundary_payload,
        "application/geo+json",
    )
    boundary = _register_layer(
        session,
        workspace=workspace,
        creator=creator,
        source_version=source_version,
        layer_key="administrative-boundaries",
        title="Synthetic Cambodia commune boundaries",
        abstract="Synthetic commune geometry and stable identifiers decomposed from the legacy bundle.",
        data_kind="vector",
        profile_key="administrative-boundary@1.0",
        filename="synthetic-commune-boundaries.geojson",
        media_type="application/geo+json",
        representation_type="administrative_boundary",
        payload=boundary_payload,
        validation=boundary_validation,
    )
    layers: list[tuple[str, CatalogDatasetVersion, Representation]] = []
    for code in INDICATOR_CODES:
        payload = _indicator_payload(areas, code)
        filename = f"synthetic-{code}.csv"
        validation = validate_file(
            "normalised-indicator-layer@1.0", filename, payload, "text/csv"
        )
        version, representation = _register_layer(
            session,
            workspace=workspace,
            creator=creator,
            source_version=source_version,
            layer_key=f"indicator-{code}",
            title=f"Synthetic {INDICATORS[code]['label']}",
            abstract=(
                f"Normalised synthetic {code} values decomposed from the preserved legacy bundle."
            ),
            data_kind="table",
            profile_key="normalised-indicator-layer@1.0",
            filename=filename,
            media_type="text/csv",
            representation_type="normalised_indicator_table",
            payload=payload,
            validation=validation,
        )
        layers.append((code, version, representation))

    input_set_id = investment_id("input-set", f"{workspace.id}:separate-layers-1.0")
    item = session.get(InvestmentAnalysisInputSet, input_set_id)
    if item is not None:
        if item.status != "LOCKED":
            raise RuntimeError("SEPARATE_LAYER_INPUT_SET_NOT_LOCKED")
        return item
    item = InvestmentAnalysisInputSet(
        id=input_set_id,
        workspace_id=workspace.id,
        name="separate-layers-1.0",
        label="Cambodia synthetic separate layers 1.0",
        profile_mode="SEPARATE_LAYERS",
        status="DRAFT",
        study_area_ref={"country": "KH", "admin_level": "commune", "synthetic": True},
        run_mode_compatibility=["FORMAL"],
        strictest_classification="FAO_INTERNAL",
        warnings_json=[
            {
                "code": "MIGRATED_SYNTHETIC_INPUT",
                "message": "Compatibility decomposition only; no business validation performed.",
            }
        ],
        created_by=creator.id,
    )
    session.add(item)
    session.flush()
    session.add(
        InvestmentAnalysisInputMember(
            id=investment_id("input-member", f"{input_set_id}:boundary"),
            input_set_id=input_set_id,
            dataset_version_id=boundary[0].id,
            representation_id=boundary[1].id,
            input_role="administrative_boundary",
            join_key="area_code",
            geometry_field="geometry",
            required=True,
            transform_config={
                "name_field": "area_name",
                "level_field": "admin_level",
                "province_field": "province",
                "population_field": "population",
                "rice_area_field": "rice_area_ha",
                "data_quality_field": "data_quality",
            },
            ordinal=0,
        )
    )
    for ordinal, (code, version, representation) in enumerate(layers, start=1):
        session.add(
            InvestmentAnalysisInputMember(
                id=investment_id("input-member", f"{input_set_id}:{code}"),
                input_set_id=input_set_id,
                dataset_version_id=version.id,
                representation_id=representation.id,
                input_role="indicator",
                indicator_code=code,
                join_key="area_code",
                value_field="value",
                unit=INDICATORS[code]["unit"],
                direction="higher_is_priority",
                time_coverage={"start": "2026-08-28", "end": "2026-08-28"},
                required=True,
                transform_config={},
                ordinal=ordinal,
            )
        )
    session.flush()
    readiness = validate_input_set(session, item, require_published=True)
    if not readiness["ready"]:
        raise RuntimeError(f"SEPARATE_LAYER_INPUT_VALIDATION_FAILED:{readiness['errors']}")
    members = session.scalars(
        select(InvestmentAnalysisInputMember)
        .where(InvestmentAnalysisInputMember.input_set_id == item.id)
        .order_by(InvestmentAnalysisInputMember.ordinal)
    ).all()
    item.readiness_result = readiness
    item.warnings_json = [*item.warnings_json, *readiness["warnings"]]
    item.strictest_classification = readiness["strictest_classification"]
    item.checksum = checksum_json(canonical_input_set(item, list(members)))
    item.status = "LOCKED"
    item.locked_by = creator.id
    item.locked_at = _utcnow()
    return item


def _legacy_results(
    session: Session, legacy_run: LegacyAnalysisRun, areas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    areas_by_id = {area["legacy_area_id"]: area for area in areas}
    stored = session.scalars(
        select(LegacyPriorityResult)
        .where(LegacyPriorityResult.run_id == legacy_run.id)
        .order_by(LegacyPriorityResult.id)
    ).all()
    calculated = score_priority_areas(
        [dict(area) for area in areas],
        LEGACY_METHOD_SPEC,
        {
            "weights": legacy_run.weights,
            "min_rice_area_ha": legacy_run.min_rice_area_ha,
        },
    )
    calculated_by_code = {item["code"]: item for item in calculated}
    results: list[dict[str, Any]] = []
    for old in stored:
        area = areas_by_id[old.area_id]
        expected = calculated_by_code[area["code"]]
        if (
            old.score != expected["score"]
            or old.rank != expected["rank"]
            or old.eligible != expected["eligible"]
            or old.priority_band != expected["priority_band"]
            or checksum_json(old.components) != checksum_json(expected["components"])
            or list(old.missing_indicators) != list(expected["missing_indicators"])
        ):
            raise RuntimeError(
                f"LEGACY_RESULT_REGRESSION:run={legacy_run.id}:result={old.id}:area={area['code']}"
            )
        results.append(
            {
                **area,
                "result_id": str(investment_id("legacy-priority-result", str(old.id))),
                "score": old.score,
                "rank": old.rank,
                "eligible": old.eligible,
                "priority_band": old.priority_band,
                "components": old.components,
                "missing_indicators": old.missing_indicators,
                "data_completeness": expected["data_completeness"],
                "quality_adjustment": expected["quality_adjustment"],
                "source_quality_flags": {
                    **area["source_quality_flags"],
                    "legacy_result_id": old.id,
                    "migration_version": MIGRATION_VERSION,
                },
            }
        )
    if len(results) != len(areas):
        raise RuntimeError(f"LEGACY_RESULT_COUNT_MISMATCH:run={legacy_run.id}")
    return sorted(
        results,
        key=lambda item: (
            not item["eligible"],
            item["rank"] if item["rank"] is not None else 10**9,
            item["code"],
        ),
    )


def _migrate_run(
    session: Session,
    context: dict[str, Any],
    legacy_run: LegacyAnalysisRun,
    areas: list[dict[str, Any]],
    *,
    materialise_outputs: bool,
) -> bool:
    existing = session.scalar(
        select(InvestmentAnalysisRun).where(
            InvestmentAnalysisRun.legacy_run_id == legacy_run.id
        )
    )
    if existing is not None:
        if existing.status not in {"succeeded", "succeeded_with_warnings"}:
            raise RuntimeError(f"PARTIAL_NATIVE_RUN_REQUIRES_RESTORE:{legacy_run.id}")
        return False
    workspace: Workspace = context["workspace"]
    creator: User = context["legacy_user"]
    input_set: InvestmentAnalysisInputSet = context["bundle_input_set"]
    method: InvestmentMethodVersion = context["method_version"]
    scenario = context["scenarios"].get(legacy_run.scenario_key)
    if input_set is None or scenario is None:
        raise RuntimeError(f"LEGACY_RUN_GOVERNANCE_MISSING:{legacy_run.id}")
    parameters = {
        "weights": {
            code: float(legacy_run.weights.get(code, 0.0)) for code in INDICATOR_CODES
        },
        "normalised_weights": normalise_weights(
            legacy_run.weights, list(INDICATOR_CODES)
        ),
        "min_rice_area_ha": float(legacy_run.min_rice_area_ha),
        "override_provenance": {
            "source": "legacy.analysis_runs",
            "legacy_run_id": legacy_run.id,
            "business_validation": "not_performed",
        },
    }
    run_id = investment_id("legacy-run", str(legacy_run.id))
    request_document = {
        "legacy_run_id": legacy_run.id,
        "input_set_id": str(input_set.id),
        "method_version_id": str(method.id),
        "scenario_id": str(scenario.id),
        "parameters": parameters,
    }
    run = InvestmentAnalysisRun(
        id=run_id,
        workspace_id=workspace.id,
        input_set_id=input_set.id,
        method_version_id=method.id,
        scenario_id=scenario.id,
        run_mode="FORMAL",
        parameters_snapshot=parameters,
        input_set_checksum=input_set.checksum,
        method_checksum=method.checksum,
        scenario_checksum=scenario.checksum,
        requested_by=creator.id,
        idempotency_key=f"legacy-migration:{legacy_run.id}",
        request_hash=checksum_json(request_document),
        status="queued",
        progress=0,
        current_step="legacy-migration",
        code_ref=HISTORICAL_CODE_REF,
        worker_task_version="legacy-synchronous-backfill:v1",
        container_metadata={
            "historical_execution": True,
            "image_digest": None,
            "digest_verified": False,
            "migration_version": MIGRATION_VERSION,
            "unknown_fields": ["original_worker_image", "original_completion_time"],
        },
        warnings_json=[
            {
                "code": "HISTORICAL_ATTRIBUTION",
                "message": "Original actor was not recorded; attributed to the legacy workspace identity.",
            },
            {
                "code": "SYNTHETIC_DEMONSTRATOR",
                "message": DEMO_DISCLAIMER,
            },
        ],
        exclusions_json=[],
        failure_json={},
        migration_source=MIGRATION_VERSION,
        legacy_run_id=legacy_run.id,
        correlation_id=checksum_json({"legacy_run_id": legacy_run.id})[:64],
        requested_at=legacy_run.created_at,
        started_at=legacy_run.created_at,
    )
    session.add(run)
    session.flush()
    create_run_inputs(session, run, input_set)
    _mapping(session, "analysis_runs", legacy_run.id, run.id)
    session.flush()
    run.status = "running"
    run.progress = 65
    run.current_step = "materialise-results"
    migrated_results = _legacy_results(session, legacy_run, areas)
    materialise_results(session, run, migrated_results)
    session.flush()
    for old in session.scalars(
        select(LegacyPriorityResult).where(LegacyPriorityResult.run_id == legacy_run.id)
    ).all():
        _mapping(
            session,
            "priority_results",
            old.id,
            investment_id("legacy-priority-result", str(old.id)),
            legacy_run_id=legacy_run.id,
            legacy_area_id=old.area_id,
        )
    run.completed_at = legacy_run.created_at
    run.current_step = "register-output"
    if materialise_outputs:
        register_output(session, run, correlation_id=run.correlation_id)
    run.status = "succeeded_with_warnings"
    run.progress = 100
    run.current_step = "complete"
    record_event(
        session,
        action="investment.analysis.migrate",
        resource_type="analysis_run",
        resource_id=run.id,
        outcome="success",
        correlation_id=run.correlation_id,
        actor_id=creator.id,
        workspace_id=workspace.id,
        after={
            "legacy_run_id": legacy_run.id,
            "result_count": run.result_count,
            "result_checksum": run.result_checksum,
            "output_materialised": materialise_outputs,
            "migration_version": MIGRATION_VERSION,
        },
    )
    return True


def verify_backfill(session: Session) -> dict[str, Any]:
    context = _context(session)
    legacy_counts = {
        "areas": session.scalar(select(func.count(AdminArea.id))) or 0,
        "indicators": session.scalar(select(func.count(IndicatorValue.id))) or 0,
        "runs": session.scalar(select(func.count(LegacyAnalysisRun.id))) or 0,
        "results": session.scalar(select(func.count(LegacyPriorityResult.id))) or 0,
    }
    if (
        legacy_counts["areas"] != 111
        or legacy_counts["indicators"] != 777
        or legacy_counts["runs"] not in {0, 13}
        or legacy_counts["results"] != legacy_counts["runs"] * 111
    ):
        raise RuntimeError(f"LEGACY_BASELINE_CHANGED:{legacy_counts}")
    native_runs = session.scalars(
        select(InvestmentAnalysisRun)
        .where(InvestmentAnalysisRun.migration_source == MIGRATION_VERSION)
        .order_by(InvestmentAnalysisRun.legacy_run_id)
    ).all()
    if len(native_runs) != legacy_counts["runs"]:
        raise RuntimeError(f"NATIVE_RUN_COUNT_MISMATCH:{len(native_runs)}")
    checked_results = 0
    for run in native_runs:
        legacy_run = session.get(LegacyAnalysisRun, run.legacy_run_id)
        if (
            legacy_run is None
            or run.status not in {"succeeded", "succeeded_with_warnings"}
            or run.result_count != len(legacy_run.results)
            or run.output_dataset_version_id is None
        ):
            raise RuntimeError(f"NATIVE_RUN_INCOMPLETE:{run.legacy_run_id}")
        if session.scalar(
            select(func.count(InvestmentAnalysisRunInput.id)).where(
                InvestmentAnalysisRunInput.run_id == run.id
            )
        ) != 1:
            raise RuntimeError(f"RUN_INPUT_SNAPSHOT_MISSING:{run.legacy_run_id}")
        assets = session.scalar(
            select(func.count(CatalogAsset.id)).where(
                CatalogAsset.dataset_version_id == run.output_dataset_version_id
            )
        )
        representations = session.scalar(
            select(func.count(Representation.id)).where(
                Representation.dataset_version_id == run.output_dataset_version_id
            )
        )
        if assets != 3 or representations != 4:
            raise RuntimeError(
                f"OUTPUT_EVIDENCE_INCOMPLETE:{run.legacy_run_id}:{assets}:{representations}"
            )
        if not session.scalar(
            select(LineageProcess.id).where(
                LineageProcess.external_run_id == str(run.id),
                LineageProcess.module_key == "investment-prioritisation",
            )
        ):
            raise RuntimeError(f"RUN_LINEAGE_MISSING:{run.legacy_run_id}")
        for old in legacy_run.results:
            mapping = session.scalar(
                select(LegacyIdMapping).where(
                    LegacyIdMapping.entity_type == "priority_results",
                    LegacyIdMapping.legacy_id == str(old.id),
                )
            )
            native = session.get(InvestmentPriorityResult, mapping.new_id) if mapping else None
            if (
                native is None
                or native.run_id != run.id
                or native.score != old.score
                or native.rank != old.rank
                or native.eligible != old.eligible
                or native.priority_band != old.priority_band
                or checksum_json(native.contributions_json) != checksum_json(old.components)
                or native.missing_indicators != old.missing_indicators
            ):
                raise RuntimeError(f"NATIVE_RESULT_MISMATCH:{old.id}")
            checked_results += 1
    if checked_results != legacy_counts["results"]:
        raise RuntimeError(f"NATIVE_RESULT_COUNT_MISMATCH:{checked_results}")
    top = None
    if legacy_counts["runs"]:
        top = session.scalar(
            select(InvestmentPriorityResult)
            .join(InvestmentAnalysisRun, InvestmentAnalysisRun.id == InvestmentPriorityResult.run_id)
            .where(
                InvestmentAnalysisRun.legacy_run_id == 1,
                InvestmentPriorityResult.rank == 1,
            )
        )
        if not top or top.area_name != "Prey Veng Demo Commune 03" or top.score != 65.32:
            raise RuntimeError("FIXED_REGRESSION_SENTINEL_CHANGED")
    separate = session.get(
        InvestmentAnalysisInputSet,
        investment_id("input-set", f"{context['workspace'].id}:separate-layers-1.0"),
    )
    if not separate or separate.status != "LOCKED" or not separate.readiness_result.get("ready"):
        raise RuntimeError("SEPARATE_LAYER_INPUT_SET_INCOMPLETE")
    return {
        "status": "verified",
        "legacy": legacy_counts,
        "native": {
            "migrated_runs": len(native_runs),
            "migrated_results": checked_results,
            "output_versions": len(native_runs),
            "output_assets": len(native_runs) * 3,
            "locked_input_sets": 2,
            "published_separate_input_versions": 8,
        },
        "fixed_sentinel": (
            {"area": top.area_name, "score": top.score}
            if top
            else {"status": "not_applicable_on_clean_seed_without_historical_runs"}
        ),
        "legacy_source": {
            "object_key": LEGACY_SOURCE_KEY,
            "sha256": LEGACY_SOURCE_SHA256,
            "size_bytes": LEGACY_SOURCE_SIZE,
        },
    }


def backfill(*, materialise_outputs: bool, verify: bool) -> dict[str, Any]:
    created_runs = 0
    with SessionLocal() as session:
        context = _context(session)
        areas = _area_records(session)
        _ensure_separate_layers(session, context, areas)
        session.commit()
    with SessionLocal() as session:
        context = _context(session)
        areas = _area_records(session)
        legacy_runs = session.scalars(
            select(LegacyAnalysisRun).order_by(LegacyAnalysisRun.id)
        ).all()
        legacy_run_count = len(legacy_runs)
        for legacy_run in legacy_runs:
            try:
                if _migrate_run(
                    session,
                    context,
                    legacy_run,
                    areas,
                    materialise_outputs=materialise_outputs,
                ):
                    created_runs += 1
                session.commit()
            except Exception:
                session.rollback()
                raise
    result: dict[str, Any] = {
        "status": "backfilled",
        "created_runs": created_runs,
        "existing_runs": legacy_run_count - created_runs,
        "materialised_outputs": materialise_outputs,
    }
    if verify:
        with SessionLocal() as session:
            result["verification"] = verify_backfill(session)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently migrate the preserved investment demonstrator into investment.*"
    )
    parser.add_argument(
        "--materialise-outputs",
        action="store_true",
        help="Register checksummed CSV, GeoJSON and run manifest assets for historical runs.",
    )
    parser.add_argument("--verify", action="store_true", help="Run exact row and evidence checks.")
    args = parser.parse_args()
    print(
        json.dumps(
            backfill(materialise_outputs=args.materialise_outputs, verify=args.verify),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
