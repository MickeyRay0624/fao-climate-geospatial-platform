from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely import wkt
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.validation import make_valid

from app.catalog import INDICATORS


BASE_REQUIRED_FIELDS = {"code", "name", "province", "rice_area_ha"}
CAMBODIA_DEMO_BOUNDS = (102.0, 10.0, 108.0, 15.0)


@dataclass
class QualityResult:
    code: str
    name: str
    status: str
    severity: str
    details: str
    affected_count: int = 0


@dataclass
class IngestedArea:
    code: str
    name: str
    province: str
    population: int
    rice_area_ha: float
    data_quality: float
    geometry: MultiPolygon
    indicators: dict[str, float | None]


@dataclass
class ParsedUpload:
    records: list[IngestedArea]
    checks: list[QualityResult]
    schema_summary: dict[str, Any]

    @property
    def has_failures(self) -> bool:
        return any(check.status == "failed" for check in self.checks)


def supported_media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".geojson", ".json"}:
        return "application/geo+json"
    if suffix == ".csv":
        return "text/csv"
    return "application/octet-stream"


def _to_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_geometry(raw_geometry: Any) -> MultiPolygon | None:
    try:
        geometry = make_valid(raw_geometry)
    except Exception:
        return None
    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry])
    if isinstance(geometry, MultiPolygon):
        return geometry
    if hasattr(geometry, "geoms"):
        polygons = [part for part in geometry.geoms if isinstance(part, Polygon)]
        if polygons:
            return MultiPolygon(polygons)
    return None


def _raw_records(filename: str, payload: bytes) -> tuple[list[tuple[dict[str, Any], Any]], set[str]]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".geojson", ".json"}:
        document = json.loads(payload.decode("utf-8-sig"))
        if document.get("type") != "FeatureCollection":
            raise ValueError("GeoJSON must be a FeatureCollection")
        rows: list[tuple[dict[str, Any], Any]] = []
        fields: set[str] = set()
        for feature in document.get("features", []):
            properties = feature.get("properties") or {}
            fields.update(properties)
            geometry_payload = feature.get("geometry")
            geometry = shape(geometry_payload) if geometry_payload else None
            rows.append((properties, geometry))
        return rows, fields

    if suffix == ".csv":
        text_stream = io.StringIO(payload.decode("utf-8-sig"))
        reader = csv.DictReader(text_stream)
        fields = set(reader.fieldnames or [])
        rows = []
        for row in reader:
            geometry_text = row.pop("geometry_wkt", "")
            geometry = wkt.loads(geometry_text) if geometry_text else None
            rows.append((dict(row), geometry))
        return rows, fields

    raise ValueError("Supported uploads are GeoJSON (.geojson/.json) and CSV with geometry_wkt")


def parse_upload(filename: str, payload: bytes) -> ParsedUpload:
    suffix = Path(filename).suffix.lower()
    format_supported = suffix in {".geojson", ".json", ".csv"}
    checks: list[QualityResult] = [
        QualityResult(
            code="file_format",
            name="Supported file format",
            status="passed" if format_supported else "failed",
            severity="error",
            details=(
                "Recognised analysis bundle format."
                if format_supported
                else "Use GeoJSON, JSON, or CSV with a geometry_wkt column."
            ),
            affected_count=0 if format_supported else 1,
        )
    ]
    if not format_supported:
        return ParsedUpload(records=[], checks=checks, schema_summary={})

    try:
        raw_rows, fields = _raw_records(filename, payload)
    except Exception as error:
        checks.append(
            QualityResult(
                code="parseable",
                name="File can be parsed",
                status="failed",
                severity="error",
                details=f"The file could not be parsed: {error}",
                affected_count=1,
            )
        )
        return ParsedUpload(records=[], checks=checks, schema_summary={})

    required_fields = BASE_REQUIRED_FIELDS | set(INDICATORS)
    if suffix == ".csv":
        required_fields = required_fields | {"geometry_wkt"}
    missing_columns = sorted(required_fields - fields)
    checks.append(
        QualityResult(
            code="required_columns",
            name="Required analysis fields",
            status="failed" if missing_columns else "passed",
            severity="error",
            details=(
                f"Missing columns: {', '.join(missing_columns)}"
                if missing_columns
                else "All required commune and indicator fields are present."
            ),
            affected_count=len(missing_columns),
        )
    )

    records: list[IngestedArea] = []
    codes: set[str] = set()
    duplicate_count = 0
    invalid_geometry_count = 0
    invalid_numeric_count = 0
    out_of_range_count = 0
    missing_indicator_count = 0
    outside_extent_count = 0
    incomplete_row_count = 0

    for properties, raw_geometry in raw_rows:
        if any(properties.get(field) in {None, ""} for field in BASE_REQUIRED_FIELDS):
            incomplete_row_count += 1
            continue

        code = str(properties["code"]).strip()
        if code in codes:
            duplicate_count += 1
        codes.add(code)

        geometry = _normalise_geometry(raw_geometry) if raw_geometry is not None else None
        if geometry is None or geometry.is_empty:
            invalid_geometry_count += 1
            continue
        min_x, min_y, max_x, max_y = geometry.bounds
        if min_x < -180 or max_x > 180 or min_y < -90 or max_y > 90:
            invalid_geometry_count += 1
            continue
        demo_min_x, demo_min_y, demo_max_x, demo_max_y = CAMBODIA_DEMO_BOUNDS
        if (
            max_x < demo_min_x
            or min_x > demo_max_x
            or max_y < demo_min_y
            or min_y > demo_max_y
        ):
            outside_extent_count += 1

        rice_area = _to_float(properties.get("rice_area_ha"))
        population = _to_float(properties.get("population"), 0)
        data_quality = _to_float(properties.get("data_quality"), 0.8)
        if rice_area is None or population is None or data_quality is None:
            invalid_numeric_count += 1
            continue
        if rice_area < 0 or population < 0 or not 0 <= data_quality <= 1:
            invalid_numeric_count += 1

        indicators: dict[str, float | None] = {}
        for indicator_code in INDICATORS:
            raw_value = properties.get(indicator_code)
            value = _to_float(raw_value)
            if raw_value not in {None, ""} and value is None:
                invalid_numeric_count += 1
            if value is None:
                missing_indicator_count += 1
            elif not 0 <= value <= 1:
                out_of_range_count += 1
            indicators[indicator_code] = value

        records.append(
            IngestedArea(
                code=code,
                name=str(properties["name"]).strip(),
                province=str(properties["province"]).strip(),
                population=int(population),
                rice_area_ha=float(rice_area),
                data_quality=float(data_quality),
                geometry=geometry,
                indicators=indicators,
            )
        )

    checks.extend(
        [
            QualityResult(
                code="record_count",
                name="Usable spatial records",
                status="passed" if records else "failed",
                severity="error",
                details=(
                    f"{len(records)} spatial records are available for import."
                    if records
                    else "No usable spatial records were found."
                ),
                affected_count=0 if records else len(raw_rows),
            ),
            QualityResult(
                code="row_completeness",
                name="Required values per row",
                status="failed" if incomplete_row_count else "passed",
                severity="error",
                details=(
                    f"{incomplete_row_count} rows lack a code, name, province, or rice area."
                    if incomplete_row_count
                    else "Every imported row has the required commune values."
                ),
                affected_count=incomplete_row_count,
            ),
            QualityResult(
                code="unique_codes",
                name="Unique commune codes",
                status="failed" if duplicate_count else "passed",
                severity="error",
                details=(
                    f"{duplicate_count} duplicate commune codes were detected."
                    if duplicate_count
                    else "Commune codes are unique within this version."
                ),
                affected_count=duplicate_count,
            ),
            QualityResult(
                code="geometry_validity",
                name="Valid polygon geometry",
                status="failed" if invalid_geometry_count else "passed",
                severity="error",
                details=(
                    f"{invalid_geometry_count} records have missing or unusable polygon geometry."
                    if invalid_geometry_count
                    else "All imported geometries are valid polygons in geographic coordinates."
                ),
                affected_count=invalid_geometry_count,
            ),
            QualityResult(
                code="numeric_values",
                name="Numeric field validity",
                status="failed" if invalid_numeric_count else "passed",
                severity="error",
                details=(
                    f"{invalid_numeric_count} invalid or negative numeric values were detected."
                    if invalid_numeric_count
                    else "Population, rice area, and data-quality values are valid."
                ),
                affected_count=invalid_numeric_count,
            ),
            QualityResult(
                code="indicator_ranges",
                name="Indicator range 0–1",
                status="failed" if out_of_range_count else "passed",
                severity="error",
                details=(
                    f"{out_of_range_count} indicator values fall outside the required 0–1 range."
                    if out_of_range_count
                    else "All available indicator values fall within 0–1."
                ),
                affected_count=out_of_range_count,
            ),
            QualityResult(
                code="missing_indicators",
                name="Indicator completeness",
                status="warning" if missing_indicator_count else "passed",
                severity="warning",
                details=(
                    f"{missing_indicator_count} indicator cells are missing; analysis will flag them."
                    if missing_indicator_count
                    else "No indicator values are missing."
                ),
                affected_count=missing_indicator_count,
            ),
            QualityResult(
                code="cambodia_extent",
                name="Cambodia extent plausibility",
                status="warning" if outside_extent_count else "passed",
                severity="warning",
                details=(
                    f"{outside_extent_count} geometries fall outside the expected Cambodia extent."
                    if outside_extent_count
                    else "All geometries fall within the expected Cambodia extent."
                ),
                affected_count=outside_extent_count,
            ),
        ]
    )

    schema_summary = {
        "format": "GeoJSON" if suffix in {".geojson", ".json"} else "CSV + WKT",
        "crs": "EPSG:4326",
        "geometry_type": "MultiPolygon",
        "fields": sorted(fields),
        "indicators": list(INDICATORS),
    }
    return ParsedUpload(records=records, checks=checks, schema_summary=schema_summary)
