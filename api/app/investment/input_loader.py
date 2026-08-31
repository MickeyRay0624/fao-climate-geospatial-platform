from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from shapely.geometry import MultiPolygon, shape

from app.ingestion import parse_upload
from app.investment.constants import INDICATOR_CODES
from app.investment.engine import ScoringContractError
from app.object_store import get_bytes
from app.platform_models import InvestmentAnalysisRunInput


def _payload(item: InvestmentAnalysisRunInput) -> bytes:
    if not item.object_key:
        raise ScoringContractError(f"Input {item.id} has no immutable object locator")
    payload = get_bytes(item.object_key)
    digest = hashlib.sha256(payload).hexdigest()
    if item.object_sha256 and digest != item.object_sha256:
        raise ScoringContractError(f"Input checksum mismatch for {item.dataset_version_id}")
    return payload


def _multi_polygon(geometry: dict[str, Any]) -> dict[str, Any]:
    parsed = shape(geometry)
    if parsed.geom_type == "Polygon":
        parsed = MultiPolygon([parsed])
    if parsed.geom_type != "MultiPolygon" or parsed.is_empty or not parsed.is_valid:
        raise ScoringContractError("Boundary geometry must be a valid Polygon or MultiPolygon")
    return parsed.__geo_interface__


def prepare_legacy_bundle(item: InvestmentAnalysisRunInput) -> list[dict[str, Any]]:
    filename = item.config_snapshot.get("filename", "analysis-bundle.geojson")
    parsed = parse_upload(filename, _payload(item))
    if any(check.status == "failed" for check in parsed.checks):
        failed = [check.code for check in parsed.checks if check.status == "failed"]
        raise ScoringContractError(f"Legacy bundle is no longer ready: {', '.join(failed)}")
    return [
        {
            "code": record.code,
            "name": record.name,
            "admin_level": item.config_snapshot.get("admin_level", "commune"),
            "province": record.province,
            "population": record.population,
            "rice_area_ha": record.rice_area_ha,
            "data_quality": record.data_quality,
            "geometry": _multi_polygon(record.geometry.__geo_interface__),
            "indicators": dict(record.indicators),
            "source_quality_flags": {"profile": "analysis-ready-priority-bundle@1.0"},
        }
        for record in parsed.records
    ]


def _read_boundary(item: InvestmentAnalysisRunInput) -> dict[str, dict[str, Any]]:
    document = json.loads(_payload(item).decode("utf-8-sig"))
    if document.get("type") != "FeatureCollection":
        raise ScoringContractError("Administrative boundary must be a GeoJSON FeatureCollection")
    config = item.config_snapshot
    code_field = config.get("join_key", "area_code")
    name_field = config.get("name_field", "area_name")
    level_field = config.get("level_field", "admin_level")
    rows: dict[str, dict[str, Any]] = {}
    for feature in document.get("features", []):
        properties = feature.get("properties") or {}
        code = str(properties.get(code_field, "")).strip()
        if not code:
            raise ScoringContractError("Administrative boundary contains a missing area code")
        if code in rows:
            raise ScoringContractError(f"Duplicate boundary area code: {code}")
        try:
            rice_area = float(properties[config.get("rice_area_field", "rice_area_ha")])
        except (KeyError, TypeError, ValueError) as error:
            raise ScoringContractError(f"Boundary {code} has no numeric rice_area_ha") from error
        rows[code] = {
            "code": code,
            "name": str(properties.get(name_field, code)),
            "admin_level": str(properties.get(level_field, "unknown/not_recorded")),
            "province": properties.get(config.get("province_field", "province")),
            "population": properties.get(config.get("population_field", "population")),
            "rice_area_ha": rice_area,
            "data_quality": properties.get(config.get("data_quality_field", "data_quality")),
            "geometry": _multi_polygon(feature.get("geometry")),
            "indicators": {},
            "source_quality_flags": {"boundary_dataset_version_id": str(item.dataset_version_id)},
        }
    if not rows:
        raise ScoringContractError("Administrative boundary contains no areas")
    return rows


def _indicator_rows(item: InvestmentAnalysisRunInput) -> dict[str, float | None]:
    payload = _payload(item)
    config = item.config_snapshot
    join_key = config.get("join_key", "area_code")
    value_field = config.get("value_field", "value")
    suffix = Path(config.get("filename", item.representation_locator)).suffix.lower()
    if suffix in {".geojson", ".json"}:
        document = json.loads(payload.decode("utf-8-sig"))
        raw_rows = [dict(feature.get("properties") or {}) for feature in document.get("features", [])]
    else:
        raw_rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    values: dict[str, float | None] = {}
    for row in raw_rows:
        code = str(row.get(join_key, "")).strip()
        if not code:
            raise ScoringContractError(f"Indicator {item.indicator_code} contains a missing area code")
        if code in values:
            raise ScoringContractError(f"Duplicate indicator area code: {code}")
        raw_value = row.get(value_field)
        if raw_value is None or str(raw_value).strip() == "":
            values[code] = None
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as error:
            raise ScoringContractError(
                f"Indicator {item.indicator_code} for {code} is not numeric"
            ) from error
        if not 0 <= value <= 1:
            raise ScoringContractError(
                f"Indicator {item.indicator_code} for {code} is outside 0-1"
            )
        values[code] = value
    return values


def prepare_separate_layers(inputs: list[InvestmentAnalysisRunInput]) -> list[dict[str, Any]]:
    boundaries = [item for item in inputs if item.input_role == "administrative_boundary"]
    indicators = [item for item in inputs if item.input_role == "indicator"]
    if len(boundaries) != 1:
        raise ScoringContractError("Separate-layer inputs require exactly one administrative boundary")
    by_code = _read_boundary(boundaries[0])
    indicator_map = {item.indicator_code: item for item in indicators}
    missing_roles = sorted(set(INDICATOR_CODES) - set(indicator_map))
    if missing_roles:
        raise ScoringContractError(f"Missing required indicator roles: {', '.join(missing_roles)}")
    if len(indicator_map) != len(indicators):
        raise ScoringContractError("An indicator role is duplicated")
    boundary_codes = set(by_code)
    for indicator_code in INDICATOR_CODES:
        values = _indicator_rows(indicator_map[indicator_code])
        missing_codes = sorted(boundary_codes - set(values))
        extra_codes = sorted(set(values) - boundary_codes)
        if missing_codes or extra_codes:
            raise ScoringContractError(
                f"Indicator {indicator_code} area-code mismatch: "
                f"missing={missing_codes[:5]}, extra={extra_codes[:5]}"
            )
        for code, value in values.items():
            by_code[code]["indicators"][indicator_code] = value
            by_code[code]["source_quality_flags"][indicator_code] = str(
                indicator_map[indicator_code].dataset_version_id
            )
    return [by_code[code] for code in sorted(by_code)]


def prepare_run_inputs(inputs: list[InvestmentAnalysisRunInput]) -> list[dict[str, Any]]:
    bundles = [item for item in inputs if item.input_role == "legacy_priority_bundle"]
    if bundles:
        if len(inputs) != 1 or len(bundles) != 1:
            raise ScoringContractError("Legacy bundle mode accepts exactly one input")
        return prepare_legacy_bundle(bundles[0])
    return prepare_separate_layers(inputs)
