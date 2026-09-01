from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from geoalchemy2.shape import from_shape
from minio.error import S3Error
from shapely.geometry import MultiPolygon, shape
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit_service import record_event
from app.authorization import can_access_dataset
from app.config import DEMO_DISCLAIMER
from app.datahub.validators import validate_file
from app.errors import conflict, not_found
from app.identity import Principal
from app.investment.canonical import canonical_json, checksum_json
from app.investment.constants import (
    INDICATOR_CODES,
    METHOD_IMPLEMENTATION_KEY,
    strictest_classification,
)
from app.investment.engine import normalise_weights, result_checksum
from app.object_store import get_bytes, presigned_get, put_bytes
from app.platform_models import (
    AuditEvent,
    CatalogAsset,
    CatalogDataset,
    CatalogDatasetVersion,
    InvestmentAnalysisInputMember,
    InvestmentAnalysisInputSet,
    InvestmentAnalysisRun,
    InvestmentAnalysisRunInput,
    InvestmentMethodDefinition,
    InvestmentMethodVersion,
    InvestmentPriorityResult,
    InvestmentRunComparison,
    InvestmentScenario,
    LineageEdge,
    LineageProcess,
    MetadataRecord,
    Representation,
)


OUTPUT_NAMESPACE = uuid.UUID("bc5fd25b-49b1-54d6-b507-daa8031969a2")


def stable_output_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(OUTPUT_NAMESPACE, f"{kind}:{value}")


def now() -> datetime:
    return datetime.now(timezone.utc)


def put_immutable_verified(object_key: str, payload: bytes, media_type: str) -> str:
    """Create a content-addressed-by-metadata object once and verify every reuse."""

    expected = hashlib.sha256(payload).hexdigest()
    try:
        stored = get_bytes(object_key)
    except S3Error as error:
        if error.code not in {"NoSuchKey", "NoSuchObject", "NotFound"}:
            raise
        put_bytes(object_key, payload, media_type)
        stored = get_bytes(object_key)
    actual = hashlib.sha256(stored).hexdigest()
    if actual != expected or len(stored) != len(payload):
        raise RuntimeError(
            f"IMMUTABLE_OBJECT_CONFLICT:{object_key}:expected={expected}:actual={actual}"
        )
    return actual


def method_checksum(specification: dict[str, Any]) -> str:
    return checksum_json(specification)


def scenario_checksum(parameters: dict[str, Any]) -> str:
    return checksum_json(parameters)


def validate_method_spec(specification: dict[str, Any]) -> None:
    required = [item.get("code") for item in specification.get("required_indicators", [])]
    if required != list(INDICATOR_CODES):
        raise conflict(
            "METHOD_SPEC_INVALID",
            "The Phase 2A legacy method must declare the seven indicators in canonical order.",
            required=required,
        )
    allowed = set(specification.get("allowed_overrides", []))
    if not allowed <= {"weights", "min_rice_area_ha"}:
        raise conflict("METHOD_SPEC_INVALID", "The method declares unsupported parameter overrides.")
    if float(specification.get("missing_values", {}).get("neutral_value", -1)) != 0.5:
        raise conflict("METHOD_SPEC_INVALID", "The preserved method requires neutral missing value 0.5.")


def validate_scenario_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    weights = parameters.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(INDICATOR_CODES):
        raise conflict("SCENARIO_PARAMETERS_INVALID", "Scenario weights must cover exactly seven indicators.")
    normalised = normalise_weights(weights, list(INDICATOR_CODES))
    minimum = float(parameters.get("min_rice_area_ha", 750.0))
    if not 0 <= minimum <= 10000:
        raise conflict("SCENARIO_PARAMETERS_INVALID", "min_rice_area_ha must be between 0 and 10000.")
    return {
        "weights": {code: float(weights[code]) for code in INDICATOR_CODES},
        "normalised_weights": normalised,
        "min_rice_area_ha": minimum,
    }


def _asset_for_representation(
    session: Session, version_id: uuid.UUID, representation: Representation
) -> CatalogAsset | None:
    asset = session.scalar(
        select(CatalogAsset).where(
            CatalogAsset.dataset_version_id == version_id,
            CatalogAsset.object_key == representation.locator,
        )
    )
    if asset is None:
        asset = session.scalar(
            select(CatalogAsset)
            .where(CatalogAsset.dataset_version_id == version_id)
            .order_by(CatalogAsset.created_at)
            .limit(1)
        )
    return asset


def input_member_payload(member: InvestmentAnalysisInputMember) -> dict[str, Any]:
    return {
        "id": str(member.id),
        "dataset_version_id": str(member.dataset_version_id),
        "representation_id": str(member.representation_id),
        "input_role": member.input_role,
        "indicator_code": member.indicator_code,
        "join_key": member.join_key,
        "value_field": member.value_field,
        "geometry_field": member.geometry_field,
        "unit": member.unit,
        "direction": member.direction,
        "time_coverage": member.time_coverage,
        "required": member.required,
        "transform_config": member.transform_config,
        "ordinal": member.ordinal,
    }


def canonical_input_set(
    input_set: InvestmentAnalysisInputSet, members: list[InvestmentAnalysisInputMember]
) -> dict[str, Any]:
    return {
        "workspace_id": str(input_set.workspace_id),
        "name": input_set.name,
        "label": input_set.label,
        "profile_mode": input_set.profile_mode,
        "study_area_ref": input_set.study_area_ref,
        "run_mode_compatibility": input_set.run_mode_compatibility,
        "members": [
            {
                key: value
                for key, value in input_member_payload(member).items()
                if key != "id"
            }
            for member in sorted(members, key=lambda item: (item.ordinal, str(item.id)))
        ],
    }


def input_set_payload(session: Session, item: InvestmentAnalysisInputSet) -> dict[str, Any]:
    members = session.scalars(
        select(InvestmentAnalysisInputMember)
        .where(InvestmentAnalysisInputMember.input_set_id == item.id)
        .order_by(InvestmentAnalysisInputMember.ordinal)
    ).all()
    return {
        "id": str(item.id),
        "workspace_id": str(item.workspace_id),
        "name": item.name,
        "label": item.label,
        "profile_mode": item.profile_mode,
        "status": item.status,
        "study_area_ref": item.study_area_ref,
        "run_mode_compatibility": item.run_mode_compatibility,
        "strictest_classification": item.strictest_classification,
        "readiness": item.readiness_result,
        "warnings": item.warnings_json,
        "checksum": item.checksum,
        "created_by": str(item.created_by),
        "locked_by": str(item.locked_by) if item.locked_by else None,
        "row_version": item.row_version,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "locked_at": item.locked_at.isoformat() if item.locked_at else None,
        "retired_at": item.retired_at.isoformat() if item.retired_at else None,
        "members": [input_member_payload(member) for member in members],
    }


def validate_input_set(
    session: Session,
    input_set: InvestmentAnalysisInputSet,
    principal: Principal | None = None,
    *,
    require_published: bool = False,
) -> dict[str, Any]:
    members = session.scalars(
        select(InvestmentAnalysisInputMember)
        .where(InvestmentAnalysisInputMember.input_set_id == input_set.id)
        .order_by(InvestmentAnalysisInputMember.ordinal)
    ).all()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    classifications: list[str] = []
    expected_profiles = {
        "legacy_priority_bundle": "analysis-ready-priority-bundle@1.0",
        "administrative_boundary": "administrative-boundary@1.0",
        "indicator": "normalised-indicator-layer@1.0",
    }
    roles = [member.input_role for member in members]
    if input_set.profile_mode == "LEGACY_BUNDLE":
        if roles != ["legacy_priority_bundle"]:
            errors.append({"code": "INPUT_ROLE_SET_INVALID", "message": "Legacy bundle mode requires exactly one bundle member."})
    elif input_set.profile_mode == "SEPARATE_LAYERS":
        if roles.count("administrative_boundary") != 1:
            errors.append({"code": "BOUNDARY_ROLE_INVALID", "message": "Separate layers require exactly one boundary."})
        indicator_codes = [member.indicator_code for member in members if member.input_role == "indicator"]
        if sorted(indicator_codes) != sorted(INDICATOR_CODES):
            errors.append({"code": "INDICATOR_ROLES_INVALID", "message": "Separate layers require each of the seven indicators exactly once.", "actual": indicator_codes})
    else:
        errors.append({"code": "INPUT_PROFILE_MODE_INVALID", "message": "Unsupported input profile mode."})

    for member in members:
        version = session.get(CatalogDatasetVersion, member.dataset_version_id)
        representation = session.get(Representation, member.representation_id)
        dataset = session.get(CatalogDataset, version.dataset_id) if version else None
        expected_profile = expected_profiles.get(member.input_role)
        member_errors: list[str] = []
        if version is None or dataset is None:
            member_errors.append("DATASET_VERSION_NOT_FOUND")
        elif version.profile_key != expected_profile:
            member_errors.append("PROFILE_MISMATCH")
        elif require_published and version.state != "PUBLISHED":
            member_errors.append("PUBLISHED_INPUT_REQUIRED")
        elif version.state not in {"VALIDATED", "APPROVED", "PUBLISHED"}:
            member_errors.append("INPUT_VERSION_NOT_READY")
        if representation is None or representation.dataset_version_id != member.dataset_version_id:
            member_errors.append("REPRESENTATION_MISMATCH")
        elif representation.status != "READY":
            member_errors.append("REPRESENTATION_NOT_READY")
        if principal and dataset and not can_access_dataset(session, principal, dataset, "dataset.download"):
            member_errors.append("INPUT_ACCESS_DENIED")
        validation_status = "NOT_RUN"
        asset = None
        if not member_errors and version and representation:
            asset = _asset_for_representation(session, version.id, representation)
            if asset is None:
                member_errors.append("INPUT_ASSET_NOT_FOUND")
            else:
                try:
                    result = validate_file(
                        version.profile_key,
                        asset.filename,
                        get_bytes(asset.object_key),
                        asset.media_type,
                    )
                    validation_status = result.status
                    for issue in result.issues:
                        target = errors if issue.severity == "BLOCKING" else warnings
                        target.append({
                            "code": issue.code,
                            "message": issue.message,
                            "member_id": str(member.id),
                            "affected_count": issue.affected_count,
                        })
                except Exception as error:
                    member_errors.append("INPUT_VALIDATION_FAILED")
                    warnings.append({"code": "VALIDATOR_EXCEPTION", "message": str(error), "member_id": str(member.id)})
        if dataset:
            classifications.append(dataset.classification)
        for code in member_errors:
            errors.append({"code": code, "member_id": str(member.id), "message": code.replace("_", " ").title()})
        evidence.append({
            "member_id": str(member.id),
            "dataset_version_id": str(member.dataset_version_id),
            "representation_id": str(member.representation_id),
            "profile": version.profile_key if version else None,
            "version_state": version.state if version else None,
            "asset_sha256": asset.sha256 if asset else None,
            "validation_status": validation_status,
        })

    canonical = canonical_input_set(input_set, list(members))
    return {
        "ready": not errors,
        "checked_at": now().isoformat(),
        "errors": errors,
        "warnings": warnings,
        "evidence": evidence,
        "strictest_classification": strictest_classification(classifications),
        "canonical_checksum": checksum_json(canonical),
    }


def method_version_payload(session: Session, item: InvestmentMethodVersion) -> dict[str, Any]:
    definition = session.get(InvestmentMethodDefinition, item.method_id)
    return {
        "id": str(item.id),
        "method_id": str(item.method_id),
        "method_key": definition.method_key if definition else None,
        "method_name": definition.name if definition else None,
        "version_label": item.version_label,
        "state": item.state,
        "specification": item.specification_json,
        "checksum": item.checksum,
        "implementation_key": item.implementation_key,
        "code_ref": item.code_ref,
        "container_metadata": item.container_metadata,
        "validation_evidence": item.validation_evidence,
        "disclaimer": item.disclaimer,
        "created_by": str(item.created_by),
        "submitted_by": str(item.submitted_by) if item.submitted_by else None,
        "approved_by": str(item.approved_by) if item.approved_by else None,
        "row_version": item.row_version,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "submitted_at": item.submitted_at.isoformat() if item.submitted_at else None,
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
    }


def scenario_payload(item: InvestmentScenario) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "workspace_id": str(item.workspace_id),
        "scenario_key": item.scenario_key,
        "version_label": item.version_label,
        "name": item.name,
        "description": item.description,
        "method_version_id": str(item.method_version_id),
        "state": item.state,
        "parameters": item.parameters_json,
        "checksum": item.checksum,
        "disclaimer": item.disclaimer,
        "created_by": str(item.created_by),
        "submitted_by": str(item.submitted_by) if item.submitted_by else None,
        "approved_by": str(item.approved_by) if item.approved_by else None,
        "row_version": item.row_version,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "submitted_at": item.submitted_at.isoformat() if item.submitted_at else None,
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
    }


def run_input_payload(item: InvestmentAnalysisRunInput, *, expose_locator: bool = False) -> dict[str, Any]:
    payload = {
        "id": str(item.id),
        "dataset_version_id": str(item.dataset_version_id),
        "representation_id": str(item.representation_id),
        "input_role": item.input_role,
        "indicator_code": item.indicator_code,
        "object_sha256": item.object_sha256,
        "representation_type": item.representation_type,
        "config": item.config_snapshot,
        "ordinal": item.ordinal,
    }
    if expose_locator:
        payload["object_key"] = item.object_key
        payload["representation_locator"] = item.representation_locator
    return payload


def run_payload(session: Session, run: InvestmentAnalysisRun, *, detail: bool = False) -> dict[str, Any]:
    input_set = session.get(InvestmentAnalysisInputSet, run.input_set_id)
    method = session.get(InvestmentMethodVersion, run.method_version_id)
    scenario = session.get(InvestmentScenario, run.scenario_id)
    payload = {
        "id": str(run.id),
        "workspace_id": str(run.workspace_id),
        "input_set": {"id": str(run.input_set_id), "label": input_set.label if input_set else None},
        "method_version": {"id": str(run.method_version_id), "version_label": method.version_label if method else None},
        "scenario": {"id": str(run.scenario_id), "name": scenario.name if scenario else None, "version_label": scenario.version_label if scenario else None},
        "run_mode": run.run_mode,
        "status": run.status,
        "progress": run.progress,
        "current_step": run.current_step,
        "requested_by": str(run.requested_by),
        "processing_job_id": str(run.processing_job_id) if run.processing_job_id else None,
        "warnings": run.warnings_json,
        "exclusions": run.exclusions_json,
        "failure": run.failure_json or None,
        "result_count": run.result_count,
        "result_checksum": run.result_checksum,
        "output_dataset_id": str(run.output_dataset_id) if run.output_dataset_id else None,
        "output_dataset_version_id": str(run.output_dataset_version_id) if run.output_dataset_version_id else None,
        "migration_source": run.migration_source,
        "legacy_run_id": run.legacy_run_id,
        "requested_at": run.requested_at.isoformat() if run.requested_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "row_version": run.row_version,
    }
    if detail:
        inputs = session.scalars(
            select(InvestmentAnalysisRunInput)
            .where(InvestmentAnalysisRunInput.run_id == run.id)
            .order_by(InvestmentAnalysisRunInput.ordinal)
        ).all()
        payload.update({
            "parameters_snapshot": run.parameters_snapshot,
            "checksums": {
                "input_set": run.input_set_checksum,
                "method": run.method_checksum,
                "scenario": run.scenario_checksum,
            },
            "execution": {
                "code_ref": run.code_ref,
                "worker_task_version": run.worker_task_version,
                "container": run.container_metadata,
                "correlation_id": run.correlation_id,
            },
            "inputs": [run_input_payload(item) for item in inputs],
            "disclaimer": DEMO_DISCLAIMER,
        })
    return payload


def can_access_run(session: Session, principal: Principal, run: InvestmentAnalysisRun | None) -> bool:
    if run is None or run.workspace_id != principal.active_workspace_id:
        return False
    if "investment.run.view" not in principal.effective_permissions:
        return False
    inputs = session.scalars(
        select(InvestmentAnalysisRunInput).where(InvestmentAnalysisRunInput.run_id == run.id)
    ).all()
    for item in inputs:
        version = session.get(CatalogDatasetVersion, item.dataset_version_id)
        dataset = session.get(CatalogDataset, version.dataset_id) if version else None
        if not dataset or not can_access_dataset(session, principal, dataset, "dataset.view_metadata"):
            return False
    return True


def require_run_access(
    session: Session, principal: Principal, run_id: uuid.UUID
) -> InvestmentAnalysisRun:
    run = session.get(InvestmentAnalysisRun, run_id)
    if not can_access_run(session, principal, run):
        raise not_found("Analysis run")
    return run


def create_run_inputs(
    session: Session, run: InvestmentAnalysisRun, input_set: InvestmentAnalysisInputSet
) -> None:
    members = session.scalars(
        select(InvestmentAnalysisInputMember)
        .where(InvestmentAnalysisInputMember.input_set_id == input_set.id)
        .order_by(InvestmentAnalysisInputMember.ordinal)
    ).all()
    for member in members:
        representation = session.get(Representation, member.representation_id)
        version = session.get(CatalogDatasetVersion, member.dataset_version_id)
        if not representation or not version:
            raise conflict("INPUT_SNAPSHOT_FAILED", "An input member no longer resolves to an exact version and representation.")
        asset = _asset_for_representation(session, version.id, representation)
        if not asset:
            raise conflict("INPUT_SNAPSHOT_FAILED", "An input representation has no immutable asset.")
        session.add(
            InvestmentAnalysisRunInput(
                id=stable_output_id("run-input", f"{run.id}:{member.ordinal}"),
                run_id=run.id,
                input_member_id=member.id,
                dataset_version_id=version.id,
                representation_id=representation.id,
                input_role=member.input_role,
                indicator_code=member.indicator_code,
                object_key=asset.object_key,
                object_sha256=asset.sha256,
                representation_type=representation.representation_type,
                representation_locator=representation.locator,
                config_snapshot={
                    "filename": asset.filename,
                    "profile_key": version.profile_key,
                    "join_key": member.join_key,
                    "value_field": member.value_field,
                    "geometry_field": member.geometry_field,
                    "unit": member.unit,
                    "direction": member.direction,
                    "time_coverage": member.time_coverage,
                    "transform_config": member.transform_config,
                    **member.transform_config,
                },
                ordinal=member.ordinal,
            )
        )


def materialise_results(
    session: Session,
    run: InvestmentAnalysisRun,
    results: list[dict[str, Any]],
    *,
    deterministic_prefix: str | None = None,
) -> str:
    session.execute(delete(InvestmentPriorityResult).where(InvestmentPriorityResult.run_id == run.id))
    for item in results:
        geometry = shape(item["geometry"]) if item.get("geometry") else None
        if geometry and geometry.geom_type == "Polygon":
            geometry = MultiPolygon([geometry])
        identifier = (
            uuid.UUID(str(item["result_id"]))
            if item.get("result_id")
            else (
                stable_output_id("legacy-priority-result", f"{deterministic_prefix}:{item['code']}")
                if deterministic_prefix
                else uuid.uuid4()
            )
        )
        session.add(
            InvestmentPriorityResult(
                id=identifier,
                run_id=run.id,
                area_code=item["code"],
                area_name=item["name"],
                admin_level=item.get("admin_level"),
                province=item.get("province"),
                population=item.get("population"),
                rice_area_ha=float(item["rice_area_ha"]),
                data_quality=item.get("data_quality"),
                geom=from_shape(geometry, srid=4326) if geometry else None,
                score=float(item["score"]),
                rank=item.get("rank"),
                eligible=bool(item["eligible"]),
                priority_band=item["priority_band"],
                contributions_json=item["components"],
                indicators_json=item.get("indicators", {}),
                missing_indicators=item["missing_indicators"],
                completeness=float(item["data_completeness"]),
                quality_adjustment=float(item["quality_adjustment"]),
                source_quality_flags=item.get("source_quality_flags", {}),
            )
        )
    checksum = result_checksum(results)
    run.result_count = len(results)
    run.result_checksum = checksum
    return checksum


def result_records(session: Session, run_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        select(InvestmentPriorityResult, func.ST_AsGeoJSON(InvestmentPriorityResult.geom, 6))
        .where(InvestmentPriorityResult.run_id == run_id)
        .order_by(
            InvestmentPriorityResult.eligible.desc(),
            InvestmentPriorityResult.rank.asc().nulls_last(),
            InvestmentPriorityResult.area_code,
        )
    ).all()
    return [
        {
            "id": str(item.id),
            "code": item.area_code,
            "name": item.area_name,
            "admin_level": item.admin_level,
            "province": item.province,
            "population": item.population,
            "rice_area_ha": item.rice_area_ha,
            "data_quality": item.data_quality,
            "geometry": json.loads(geometry_json) if geometry_json else None,
            "score": item.score,
            "rank": item.rank,
            "eligible": item.eligible,
            "priority_band": item.priority_band,
            "components": item.contributions_json,
            "indicators": item.indicators_json,
            "missing_indicators": item.missing_indicators,
            "data_completeness": item.completeness,
            "quality_adjustment": item.quality_adjustment,
            "source_quality_flags": item.source_quality_flags,
        }
        for item, geometry_json in rows
    ]


def results_payload(session: Session, run: InvestmentAnalysisRun) -> dict[str, Any]:
    records = result_records(session, run.id)
    eligible = [record for record in records if record["eligible"]]
    return {
        "run_id": str(run.id),
        "status": run.status,
        "summary": {
            "total_areas": len(records),
            "eligible_areas": len(eligible),
            "excluded_areas": len(records) - len(eligible),
            "average_score": round(sum(item["score"] for item in eligible) / max(len(eligible), 1), 2),
            "top_area": ({"name": eligible[0]["name"], "score": eligible[0]["score"], "province": eligible[0]["province"]} if eligible else None),
            "top_10_rice_area_ha": round(sum(item["rice_area_ha"] for item in eligible[:10]), 1),
        },
        "ranking": [record for record in records if record["eligible"]],
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": record["id"],
                    "geometry": record["geometry"],
                    "properties": {key: value for key, value in record.items() if key != "geometry"},
                }
                for record in records
            ],
        },
        "result_checksum": run.result_checksum,
        "disclaimer": DEMO_DISCLAIMER,
    }


def _csv_bytes(records: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    fields = [
        "area_code", "area_name", "admin_level", "province", "rank", "score", "eligible",
        "priority_band", "rice_area_ha", "population", "data_quality", "data_completeness",
        "quality_adjustment", *INDICATOR_CODES,
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for item in records:
        writer.writerow({
            "area_code": item["code"], "area_name": item["name"], "admin_level": item["admin_level"],
            "province": item["province"], "rank": item["rank"], "score": item["score"],
            "eligible": str(item["eligible"]).lower(), "priority_band": item["priority_band"],
            "rice_area_ha": item["rice_area_ha"], "population": item["population"],
            "data_quality": item["data_quality"], "data_completeness": item["data_completeness"],
            "quality_adjustment": item["quality_adjustment"],
            **{code: item["indicators"].get(code) for code in INDICATOR_CODES},
        })
    return buffer.getvalue().encode("utf-8")


def _manifest(session: Session, run: InvestmentAnalysisRun, asset_specs: list[dict[str, Any]]) -> dict[str, Any]:
    inputs = session.scalars(
        select(InvestmentAnalysisRunInput)
        .where(InvestmentAnalysisRunInput.run_id == run.id)
        .order_by(InvestmentAnalysisRunInput.ordinal)
    ).all()
    return {
        "manifest_version": "1.0",
        "run": {
            "id": str(run.id),
            "workspace_id": str(run.workspace_id),
            "requested_by": str(run.requested_by),
            "requested_at": run.requested_at.isoformat() if run.requested_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "migration_source": run.migration_source,
            "legacy_run_id": run.legacy_run_id,
        },
        "input_set": {"id": str(run.input_set_id), "checksum": run.input_set_checksum},
        "inputs": [run_input_payload(item, expose_locator=True) for item in inputs],
        "method": {
            "method_version_id": str(run.method_version_id),
            "checksum": run.method_checksum,
            "implementation_key": METHOD_IMPLEMENTATION_KEY,
        },
        "scenario": {"scenario_id": str(run.scenario_id), "checksum": run.scenario_checksum},
        "parameters_snapshot": run.parameters_snapshot,
        "execution": {
            "code_ref": run.code_ref,
            "worker_task_version": run.worker_task_version,
            "container": run.container_metadata,
        },
        "result": {"row_count": run.result_count, "checksum": run.result_checksum},
        "assets": asset_specs,
        "disclaimer": DEMO_DISCLAIMER,
    }


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:120] or "investment-results"


def register_output(
    session: Session,
    run: InvestmentAnalysisRun,
    *,
    correlation_id: str,
) -> dict[str, Any]:
    records = result_records(session, run.id)
    if not records or len(records) != run.result_count:
        raise RuntimeError("RESULT_RECONCILIATION_FAILED")
    input_set = session.get(InvestmentAnalysisInputSet, run.input_set_id)
    dataset_slug = f"investment-priority-results-{_safe_slug(str(run.input_set_id))}"
    dataset = session.scalar(
        select(CatalogDataset).where(
            CatalogDataset.workspace_id == run.workspace_id,
            CatalogDataset.slug == dataset_slug,
        )
    )
    if dataset is None:
        dataset = CatalogDataset(
            id=stable_output_id("output-dataset", f"{run.workspace_id}:{run.input_set_id}"),
            workspace_id=run.workspace_id,
            slug=dataset_slug,
            title=f"Investment priority results — {input_set.label if input_set else run.input_set_id}",
            abstract="Immutable derived outputs from governed investment prioritisation runs.",
            data_kind="derived_product",
            owner_user_id=run.requested_by,
            visibility="WORKSPACE",
            classification=input_set.strictest_classification if input_set else "FAO_INTERNAL",
            lifecycle_status="ACTIVE",
            licence_code="DEMO-ONLY",
            created_by=run.requested_by,
            updated_by=run.requested_by,
        )
        session.add(dataset)
        session.flush()
    version = session.get(CatalogDatasetVersion, stable_output_id("output-version", str(run.id)))
    if version is None:
        version = CatalogDatasetVersion(
            id=stable_output_id("output-version", str(run.id)),
            dataset_id=dataset.id,
            version_label=f"run-{run.id}",
            state="DRAFT",
            profile_key="priority-ranking@1.0",
            change_summary=f"Derived output for immutable investment run {run.id}.",
            metadata_snapshot={},
            created_by=run.requested_by,
            created_at=run.requested_at,
        )
        session.add(version)
        session.flush()

    geojson_document = results_payload(session, run)["geojson"]
    geojson_document["metadata"] = {
        "analysis_run_id": str(run.id),
        "result_checksum": run.result_checksum,
        "synthetic": True,
        "operational_use": False,
        "disclaimer": DEMO_DISCLAIMER,
    }
    csv_payload = _csv_bytes(records)
    geojson_payload = canonical_json(geojson_document).encode("utf-8")
    prefix = f"catalog/{run.workspace_id}/datasets/{dataset.id}/versions/{version.id}/derived"
    preliminary = [
        {"filename": "priority-ranking.csv", "media_type": "text/csv", "role": "data", "payload": csv_payload},
        {"filename": "priority-ranking.geojson", "media_type": "application/geo+json", "role": "data", "payload": geojson_payload},
    ]
    asset_specs = [
        {
            "filename": item["filename"],
            "media_type": item["media_type"],
            "role": item["role"],
            "object_key": f"{prefix}/{item['filename']}",
            "size_bytes": len(item["payload"]),
            "sha256": hashlib.sha256(item["payload"]).hexdigest(),
        }
        for item in preliminary
    ]
    manifest_document = _manifest(session, run, asset_specs)
    manifest_payload = canonical_json(manifest_document).encode("utf-8")
    preliminary.append({"filename": "run-manifest.json", "media_type": "application/json", "role": "manifest", "payload": manifest_payload})
    asset_specs.append({
        "filename": "run-manifest.json", "media_type": "application/json", "role": "manifest",
        "object_key": f"{prefix}/run-manifest.json", "size_bytes": len(manifest_payload),
        "sha256": hashlib.sha256(manifest_payload).hexdigest(),
    })

    for item, spec in zip(preliminary, asset_specs, strict=True):
        put_immutable_verified(spec["object_key"], item["payload"], spec["media_type"])
        asset = session.get(CatalogAsset, stable_output_id("output-asset", f"{run.id}:{spec['filename']}"))
        if asset is None:
            session.add(CatalogAsset(
                id=stable_output_id("output-asset", f"{run.id}:{spec['filename']}"),
                dataset_version_id=version.id,
                role=spec["role"], filename=spec["filename"], object_key=spec["object_key"],
                media_type=spec["media_type"], size_bytes=spec["size_bytes"], sha256=spec["sha256"],
                scan_status="CLEAN", storage_class="STANDARD",
            ))

    representations = [
        ("postgis_table", f"investment.priority_results?run_id={run.id}", {"run_id": str(run.id), "fields": ["area_code", "score", "rank", "eligible", "priority_band", "contributions_json"]}),
        ("csv_download", asset_specs[0]["object_key"], {"asset_sha256": asset_specs[0]["sha256"]}),
        ("geojson_download", asset_specs[1]["object_key"], {"asset_sha256": asset_specs[1]["sha256"]}),
        ("run_manifest", asset_specs[2]["object_key"], {"asset_sha256": asset_specs[2]["sha256"]}),
    ]
    for index, (kind, locator, schema_json) in enumerate(representations):
        representation_id = stable_output_id("output-representation", f"{run.id}:{kind}")
        if session.get(Representation, representation_id) is None:
            session.add(Representation(
                id=representation_id, dataset_version_id=version.id, representation_type=kind,
                locator=locator, status="READY", crs="EPSG:4326" if kind in {"postgis_table", "geojson_download"} else None,
                geometry_type="MultiPolygon" if kind in {"postgis_table", "geojson_download"} else None,
                schema_json=schema_json, statistics_json={"record_count": run.result_count},
                preview_json=None,
            ))
    if session.scalar(select(MetadataRecord.id).where(MetadataRecord.dataset_version_id == version.id)) is None:
        session.add(MetadataRecord(
            id=stable_output_id("output-metadata", str(run.id)), dataset_version_id=version.id,
            title=f"Investment priority ranking run {run.id}",
            abstract="Synthetic, illustrative priority ranking generated from governed exact-version inputs.",
            purpose="Demonstrate reproducible investment prioritisation; not operational planning evidence.",
            producer="FAO Climate Geospatial Data & Decision Platform local demonstrator",
            provenance=f"Generated by investment analysis run {run.id}; see run-manifest.json.",
            licence_code="DEMO-ONLY", use_limitation=DEMO_DISCLAIMER, crs="EPSG:4326",
            methodology="Approved legacy-wlc-1.0.0 demonstrator method; exact method and parameter checksums in manifest.",
            quality_statement="Synthetic input and illustrative method. Checksums verified before registration.",
            keywords=["synthetic", "investment prioritisation", "derived product"],
            sensitive_data_declaration="No personal data; synthetic administrative geometries.",
        ))

    process_id = stable_output_id("output-lineage-process", str(run.id))
    process = session.get(LineageProcess, process_id)
    if process is None:
        process = LineageProcess(
            id=process_id, workspace_id=run.workspace_id, process_type="analysis",
            module_key="investment-prioritisation", external_run_type="investment.analysis_run",
            external_run_id=str(run.id), method_identifier="legacy-weighted-linear-combination",
            method_version="legacy-wlc-1.0.0", code_ref=run.code_ref,
            parameters_json={"parameter_checksum": checksum_json(run.parameters_snapshot), "result_checksum": run.result_checksum},
            status="SUCCEEDED", started_at=run.started_at or run.requested_at,
            completed_at=run.completed_at or now(),
        )
        session.add(process)
        session.flush()
    run_inputs = session.scalars(
        select(InvestmentAnalysisRunInput).where(InvestmentAnalysisRunInput.run_id == run.id).order_by(InvestmentAnalysisRunInput.ordinal)
    ).all()
    for index, item in enumerate(run_inputs):
        edge_id = stable_output_id("input-lineage-edge", f"{run.id}:{item.dataset_version_id}:{index}")
        if session.get(LineageEdge, edge_id) is None:
            session.add(LineageEdge(
                id=edge_id, process_id=process.id, direction="INPUT", dataset_version_id=item.dataset_version_id,
                role=item.indicator_code or item.input_role, ordinal=index,
            ))
    output_edge_id = stable_output_id("output-lineage-edge", str(run.id))
    if session.get(LineageEdge, output_edge_id) is None:
        session.add(LineageEdge(
            id=output_edge_id, process_id=process.id, direction="OUTPUT",
            dataset_version_id=version.id, role="priority-ranking", ordinal=0,
        ))
    if version.state == "DRAFT":
        version.state = "VALIDATED"
    run.output_dataset_id = dataset.id
    run.output_dataset_version_id = version.id
    record_event(
        session, action="investment.result.register", resource_type="analysis_run", resource_id=run.id,
        outcome="success", correlation_id=correlation_id, actor_id=run.requested_by,
        workspace_id=run.workspace_id,
        after={"dataset_version_id": str(version.id), "assets": [{"filename": item["filename"], "sha256": item["sha256"]} for item in asset_specs]},
    )
    return {"dataset_id": str(dataset.id), "dataset_version_id": str(version.id), "assets": asset_specs}


def asset_payloads(session: Session, run: InvestmentAnalysisRun, *, sign: bool = False) -> list[dict[str, Any]]:
    if not run.output_dataset_version_id:
        return []
    assets = session.scalars(
        select(CatalogAsset).where(CatalogAsset.dataset_version_id == run.output_dataset_version_id).order_by(CatalogAsset.filename)
    ).all()
    return [
        {
            "id": str(asset.id), "filename": asset.filename, "role": asset.role,
            "media_type": asset.media_type, "size_bytes": asset.size_bytes, "sha256": asset.sha256,
            **({"url": presigned_get(asset.object_key)} if sign else {}),
        }
        for asset in assets
    ]


def lineage_payload(session: Session, run: InvestmentAnalysisRun) -> dict[str, Any]:
    process = session.scalar(select(LineageProcess).where(LineageProcess.external_run_id == str(run.id), LineageProcess.module_key == "investment-prioritisation"))
    if not process:
        return {"run_id": str(run.id), "process": None, "edges": []}
    edges = session.scalars(select(LineageEdge).where(LineageEdge.process_id == process.id).order_by(LineageEdge.direction, LineageEdge.ordinal)).all()
    return {
        "run_id": str(run.id),
        "process": {"id": str(process.id), "status": process.status, "method_identifier": process.method_identifier, "method_version": process.method_version, "code_ref": process.code_ref},
        "edges": [{"id": str(edge.id), "direction": edge.direction, "dataset_version_id": str(edge.dataset_version_id), "role": edge.role, "ordinal": edge.ordinal} for edge in edges],
    }


def audit_payload(session: Session, run: InvestmentAnalysisRun) -> dict[str, Any]:
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.workspace_id == run.workspace_id, AuditEvent.resource_id == str(run.id)).order_by(AuditEvent.event_time)
    ).all()
    return {"items": [{"id": str(item.id), "event_time": item.event_time.isoformat(), "actor_id": str(item.actor_id) if item.actor_id else None, "action": item.action, "outcome": item.outcome, "reason": item.reason, "correlation_id": item.correlation_id, "after": item.after_json} for item in events], "meta": {"total": len(events)}}


def create_comparison(
    session: Session,
    left: InvestmentAnalysisRun,
    right: InvestmentAnalysisRun,
    *,
    actor_id: uuid.UUID,
    idempotency_key: str,
    request_hash: str,
    top_n: int,
) -> InvestmentRunComparison:
    if left.workspace_id != right.workspace_id:
        raise conflict("RUNS_NOT_COMPARABLE", "Runs from different workspaces cannot be compared.")
    if left.status not in {"succeeded", "succeeded_with_warnings"} or right.status not in {"succeeded", "succeeded_with_warnings"}:
        raise conflict("RUNS_NOT_COMPARABLE", "Both runs must have completed successfully.")
    left_rows = {item.area_code: item for item in session.scalars(select(InvestmentPriorityResult).where(InvestmentPriorityResult.run_id == left.id)).all()}
    right_rows = {item.area_code: item for item in session.scalars(select(InvestmentPriorityResult).where(InvestmentPriorityResult.run_id == right.id)).all()}
    if set(left_rows) != set(right_rows):
        raise conflict("RUNS_NOT_COMPARABLE", "Run study areas do not contain the same stable area codes.")
    area_results = []
    for code in sorted(left_rows):
        left_item, right_item = left_rows[code], right_rows[code]
        area_results.append({
            "area_code": code, "area_name": left_item.area_name,
            "left_score": left_item.score, "right_score": right_item.score,
            "score_delta": round(right_item.score - left_item.score, 12),
            "left_rank": left_item.rank, "right_rank": right_item.rank,
            "rank_delta": (right_item.rank - left_item.rank if left_item.rank is not None and right_item.rank is not None else None),
            "eligibility_change": left_item.eligible != right_item.eligible,
            "left_band": left_item.priority_band, "right_band": right_item.priority_band,
            "band_change": left_item.priority_band != right_item.priority_band,
        })
    left_top = {item.area_code for item in sorted(left_rows.values(), key=lambda row: (row.rank is None, row.rank or 10**9))[:top_n] if item.eligible}
    right_top = {item.area_code for item in sorted(right_rows.values(), key=lambda row: (row.rank is None, row.rank or 10**9))[:top_n] if item.eligible}
    summary = {
        "area_count": len(area_results),
        "changed_bands": sum(item["band_change"] for item in area_results),
        "eligibility_changes": sum(item["eligibility_change"] for item in area_results),
        "top_n": top_n,
        "top_n_overlap": len(left_top & right_top),
        "top_n_overlap_ratio": round(len(left_top & right_top) / max(len(left_top | right_top), 1), 6),
    }
    differences = {
        "input_set": {"left": str(left.input_set_id), "right": str(right.input_set_id), "different": left.input_set_checksum != right.input_set_checksum},
        "method": {"left": str(left.method_version_id), "right": str(right.method_version_id), "different": left.method_checksum != right.method_checksum},
        "scenario": {"left": str(left.scenario_id), "right": str(right.scenario_id), "different": left.scenario_checksum != right.scenario_checksum},
        "parameters": {"left": left.parameters_snapshot, "right": right.parameters_snapshot},
    }
    checksum = checksum_json({"left_run_id": str(left.id), "right_run_id": str(right.id), "summary": summary, "areas": area_results})
    comparison = InvestmentRunComparison(
        workspace_id=left.workspace_id, left_run_id=left.id, right_run_id=right.id,
        created_by=actor_id, idempotency_key=idempotency_key, request_hash=request_hash,
        compatibility_json={"compatible": True, "area_codes_checksum": checksum_json(sorted(left_rows))},
        differences_json=differences, summary_json=summary, area_results_json=area_results, checksum=checksum,
    )
    session.add(comparison)
    session.flush()
    return comparison


def comparison_payload(item: InvestmentRunComparison, *, detail: bool = True) -> dict[str, Any]:
    return {
        "id": str(item.id), "workspace_id": str(item.workspace_id),
        "left_run_id": str(item.left_run_id), "right_run_id": str(item.right_run_id),
        "created_by": str(item.created_by), "created_at": item.created_at.isoformat() if item.created_at else None,
        "compatibility": item.compatibility_json, "differences": item.differences_json,
        "summary": item.summary_json, "checksum": item.checksum,
        **({"areas": item.area_results_json} if detail else {}),
    }
