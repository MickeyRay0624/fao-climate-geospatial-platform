from __future__ import annotations

import csv
import io
import json
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import shape

from app.ingestion import parse_upload


@dataclass(slots=True)
class ValidationIssue:
    code: str
    name: str
    severity: str
    message: str
    affected_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationResult:
    profile_key: str
    record_count: int
    schema: dict[str, Any]
    preview: dict[str, Any] | list[Any] | None
    representation_type: str
    issues: list[ValidationIssue]
    bbox: list[float] | None = None
    crs: str | None = None
    geometry_type: str | None = None
    parsed_bundle: Any | None = None

    @property
    def has_blocking(self) -> bool:
        return any(issue.severity == "BLOCKING" for issue in self.issues)

    @property
    def status(self) -> str:
        if self.has_blocking:
            return "FAILED"
        if any(issue.severity == "WARNING" for issue in self.issues):
            return "WARNING"
        return "PASSED"


class FileScanner:
    def scan(self, filename: str, payload: bytes) -> str:
        raise NotImplementedError


class DevelopmentBypassScanner(FileScanner):
    def scan(self, filename: str, payload: bytes) -> str:
        return "BYPASSED_DEV"


class FailClosedScanner(FileScanner):
    def scan(self, filename: str, payload: bytes) -> str:
        raise RuntimeError("No approved malware scanner is configured")


def validate_analysis_bundle(filename: str, payload: bytes) -> ValidationResult:
    parsed = parse_upload(filename, payload)
    issues = [
        ValidationIssue(
            code=f"LEGACY_{check.code.upper()}",
            name=check.name,
            severity="BLOCKING" if check.status == "failed" else "WARNING",
            message=check.details,
            affected_count=check.affected_count,
        )
        for check in parsed.checks
        if check.status != "passed"
    ]
    preview = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": record.geometry.__geo_interface__,
                "properties": {
                    "code": record.code,
                    "name": record.name,
                    "province": record.province,
                    "rice_area_ha": record.rice_area_ha,
                    **record.indicators,
                },
            }
            for record in parsed.records[:20]
        ],
    }
    return ValidationResult(
        profile_key="analysis-ready-priority-bundle@1.0",
        record_count=len(parsed.records),
        schema=parsed.schema_summary,
        preview=preview,
        representation_type="legacy_priority_bundle",
        issues=issues,
        crs="EPSG:4326",
        geometry_type="MultiPolygon",
        parsed_bundle=parsed,
    )


def validate_generic_vector(filename: str, payload: bytes) -> ValidationResult:
    issues: list[ValidationIssue] = []
    try:
        document = json.loads(payload.decode("utf-8-sig"))
    except Exception as error:
        return ValidationResult(
            "generic-vector@1.0", 0, {}, None, "geojson_preview",
            [ValidationIssue("VECTOR_NOT_PARSEABLE", "Parseable GeoJSON", "BLOCKING", str(error), 1)],
        )
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        return ValidationResult(
            "generic-vector@1.0", 0, {}, None, "geojson_preview",
            [ValidationIssue("VECTOR_NOT_FEATURE_COLLECTION", "GeoJSON FeatureCollection", "BLOCKING", "The document must be a GeoJSON FeatureCollection.", 1)],
        )
    features = document.get("features")
    if not isinstance(features, list) or not features:
        issues.append(ValidationIssue("VECTOR_EMPTY", "Non-empty vector", "BLOCKING", "No features were found.", 1))
        features = []
    geometry_types: set[str] = set()
    fields: set[str] = set()
    invalid = 0
    bounds: list[tuple[float, float, float, float]] = []
    for feature in features:
        properties = feature.get("properties") or {}
        fields.update(properties.keys())
        raw_geometry = feature.get("geometry")
        if not raw_geometry:
            invalid += 1
            continue
        try:
            geometry = shape(raw_geometry)
            geometry_types.add(geometry.geom_type)
            if geometry.is_empty or not geometry.is_valid:
                invalid += 1
            else:
                bounds.append(geometry.bounds)
        except Exception:
            invalid += 1
    if invalid:
        issues.append(ValidationIssue("VECTOR_INVALID_GEOMETRY", "Valid geometry", "BLOCKING", f"{invalid} features have missing or invalid geometry.", invalid))
    bbox = None
    if bounds:
        bbox = [min(item[0] for item in bounds), min(item[1] for item in bounds), max(item[2] for item in bounds), max(item[3] for item in bounds)]
    crs = "EPSG:4326"
    if "crs" not in document:
        issues.append(ValidationIssue("VECTOR_CRS_ASSUMED", "Coordinate reference system", "WARNING", "No CRS declaration was supplied; GeoJSON is assumed to use EPSG:4326."))
    schema = {
        "format": "GeoJSON",
        "fields": sorted(fields),
        "geometry_types": sorted(geometry_types),
        "record_count": len(features),
    }
    return ValidationResult(
        "generic-vector@1.0",
        len(features),
        schema,
        {"type": "FeatureCollection", "features": features[:20]},
        "geojson_preview",
        issues,
        bbox=bbox,
        crs=crs,
        geometry_type=",".join(sorted(geometry_types)) or None,
    )


def _infer_scalar(value: str) -> str:
    if value == "":
        return "empty"
    try:
        int(value)
        return "integer"
    except ValueError:
        pass
    try:
        float(value)
        return "number"
    except ValueError:
        return "string"


def validate_generic_table(filename: str, payload: bytes) -> ValidationResult:
    issues: list[ValidationIssue] = []
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        return ValidationResult(
            "generic-table@1.0", 0, {}, None, "table_preview",
            [ValidationIssue("TABLE_ENCODING_INVALID", "UTF-8 encoding", "BLOCKING", str(error), 1)],
        )
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as error:
        return ValidationResult(
            "generic-table@1.0", 0, {}, None, "table_preview",
            [ValidationIssue("TABLE_NOT_PARSEABLE", "Parseable CSV", "BLOCKING", str(error), 1)],
        )
    if not rows or not rows[0]:
        return ValidationResult(
            "generic-table@1.0", 0, {}, None, "table_preview",
            [ValidationIssue("TABLE_HEADER_MISSING", "CSV header", "BLOCKING", "The CSV header is missing.", 1)],
        )
    header = rows[0]
    duplicates = sorted({name for name in header if header.count(name) > 1})
    if duplicates:
        issues.append(ValidationIssue("TABLE_DUPLICATE_COLUMNS", "Unique columns", "BLOCKING", f"Duplicate columns: {', '.join(duplicates)}", len(duplicates)))
    data_rows = rows[1:]
    malformed = sum(1 for row in data_rows if len(row) != len(header))
    empty = sum(1 for row in data_rows if not any(cell.strip() for cell in row))
    if malformed:
        issues.append(ValidationIssue("TABLE_MALFORMED_ROWS", "Consistent row width", "BLOCKING", f"{malformed} rows do not match the header width.", malformed))
    if empty:
        issues.append(ValidationIssue("TABLE_EMPTY_ROWS", "Non-empty rows", "WARNING", f"{empty} empty rows were found.", empty))
    valid_rows = [row for row in data_rows if len(row) == len(header)]
    inferred = {
        name: sorted({_infer_scalar(row[index]) for row in valid_rows[:100]})
        for index, name in enumerate(header)
    }
    preview = [dict(zip(header, row, strict=False)) for row in valid_rows[:20]]
    return ValidationResult(
        "generic-table@1.0",
        len(valid_rows),
        {"format": "CSV", "columns": header, "inferred_types": inferred, "record_count": len(valid_rows)},
        preview,
        "table_preview",
        issues,
    )


def validate_administrative_boundary(filename: str, payload: bytes) -> ValidationResult:
    base = validate_generic_vector(filename, payload)
    issues = list(base.issues)
    try:
        document = json.loads(payload.decode("utf-8-sig"))
        features = document.get("features", []) if isinstance(document, dict) else []
    except Exception:
        features = []
    required = {"area_code", "area_name", "admin_level"}
    missing_fields = sorted(required - set(base.schema.get("fields", [])))
    if missing_fields:
        issues.append(
            ValidationIssue(
                "BOUNDARY_REQUIRED_FIELDS",
                "Stable administrative identifiers",
                "BLOCKING",
                f"Missing fields: {', '.join(missing_fields)}",
                len(missing_fields),
            )
        )
    codes = [str((feature.get("properties") or {}).get("area_code", "")).strip() for feature in features]
    empty_codes = sum(not code for code in codes)
    duplicates = sorted({code for code in codes if code and codes.count(code) > 1})
    if empty_codes:
        issues.append(
            ValidationIssue(
                "BOUNDARY_AREA_CODE_MISSING", "Non-empty area codes", "BLOCKING",
                f"{empty_codes} boundary features have no area_code.", empty_codes,
            )
        )
    if duplicates:
        issues.append(
            ValidationIssue(
                "BOUNDARY_AREA_CODE_DUPLICATE", "Unique area codes", "BLOCKING",
                f"Duplicate area codes: {', '.join(duplicates[:10])}", len(duplicates),
            )
        )
    geometry_types = set(base.schema.get("geometry_types", []))
    invalid_types = geometry_types - {"Polygon", "MultiPolygon"}
    if invalid_types:
        issues.append(
            ValidationIssue(
                "BOUNDARY_GEOMETRY_TYPE", "Polygonal administrative geometry", "BLOCKING",
                f"Unsupported geometry types: {', '.join(sorted(invalid_types))}", len(invalid_types),
            )
        )
    return ValidationResult(
        "administrative-boundary@1.0",
        base.record_count,
        {**base.schema, "required_fields": sorted(required), "join_key": "area_code"},
        base.preview,
        "administrative_boundary",
        issues,
        bbox=base.bbox,
        crs=base.crs,
        geometry_type=base.geometry_type,
    )


def _normalised_indicator_rows(filename: str, payload: bytes) -> tuple[list[dict[str, Any]], str]:
    if Path(filename).suffix.lower() in {".geojson", ".json"}:
        document = json.loads(payload.decode("utf-8-sig"))
        if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
            raise ValueError("Indicator GeoJSON must be a FeatureCollection")
        return [dict(feature.get("properties") or {}) for feature in document.get("features", [])], "geojson"
    text = payload.decode("utf-8-sig")
    return [dict(row) for row in csv.DictReader(io.StringIO(text))], "csv"


def validate_normalised_indicator_layer(filename: str, payload: bytes) -> ValidationResult:
    issues: list[ValidationIssue] = []
    try:
        rows, format_name = _normalised_indicator_rows(filename, payload)
    except Exception as error:
        return ValidationResult(
            "normalised-indicator-layer@1.0", 0, {}, None, "normalised_indicator_table",
            [ValidationIssue("INDICATOR_NOT_PARSEABLE", "Parseable indicator layer", "BLOCKING", str(error), 1)],
        )
    required = {
        "area_code", "value", "indicator_code", "unit", "direction", "time_start", "time_end"
    }
    fields = set().union(*(row.keys() for row in rows)) if rows else set()
    missing_fields = sorted(required - fields)
    if missing_fields:
        issues.append(
            ValidationIssue(
                "INDICATOR_REQUIRED_FIELDS", "Declared indicator contract", "BLOCKING",
                f"Missing fields: {', '.join(missing_fields)}", len(missing_fields),
            )
        )
    codes = [str(row.get("area_code", "")).strip() for row in rows]
    duplicate_codes = sorted({code for code in codes if code and codes.count(code) > 1})
    if any(not code for code in codes):
        count = sum(not code for code in codes)
        issues.append(
            ValidationIssue("INDICATOR_AREA_CODE_MISSING", "Non-empty join keys", "BLOCKING", f"{count} rows have no area_code.", count)
        )
    if duplicate_codes:
        issues.append(
            ValidationIssue(
                "INDICATOR_AREA_CODE_DUPLICATE", "Unique join keys", "BLOCKING",
                f"Duplicate area codes: {', '.join(duplicate_codes[:10])}", len(duplicate_codes),
            )
        )
    out_of_range = 0
    missing_values = 0
    for row in rows:
        raw = row.get("value")
        if raw is None or str(raw).strip() == "":
            missing_values += 1
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            out_of_range += 1
            continue
        if not 0 <= value <= 1:
            out_of_range += 1
    if out_of_range:
        issues.append(
            ValidationIssue(
                "INDICATOR_VALUE_RANGE", "Pre-normalised 0-1 values", "BLOCKING",
                f"{out_of_range} values are non-numeric or outside 0-1.", out_of_range,
            )
        )
    if missing_values:
        issues.append(
            ValidationIssue(
                "INDICATOR_VALUES_MISSING", "Declared missing values", "WARNING",
                f"{missing_values} values are missing and will use the approved method policy.", missing_values,
            )
        )
    indicator_codes = sorted({str(row.get("indicator_code", "")).strip() for row in rows if row.get("indicator_code")})
    directions = sorted({str(row.get("direction", "")).strip() for row in rows if row.get("direction")})
    units = sorted({str(row.get("unit", "")).strip() for row in rows if row.get("unit")})
    if len(indicator_codes) != 1:
        issues.append(
            ValidationIssue("INDICATOR_CODE_INCONSISTENT", "One indicator per layer", "BLOCKING", "A layer must declare exactly one indicator_code.", len(indicator_codes))
        )
    if directions != ["higher_is_priority"]:
        issues.append(
            ValidationIssue("INDICATOR_DIRECTION_UNSUPPORTED", "Declared priority direction", "BLOCKING", "Phase 2A accepts higher_is_priority layers only.", len(directions))
        )
    if len(units) != 1:
        issues.append(
            ValidationIssue("INDICATOR_UNIT_INCONSISTENT", "One declared unit", "BLOCKING", "A layer must declare exactly one unit.", len(units))
        )
    schema = {
        "format": format_name.upper(),
        "fields": sorted(fields),
        "record_count": len(rows),
        "indicator_code": indicator_codes[0] if len(indicator_codes) == 1 else None,
        "unit": units[0] if len(units) == 1 else None,
        "direction": directions[0] if len(directions) == 1 else None,
        "join_key": "area_code",
        "value_field": "value",
    }
    return ValidationResult(
        "normalised-indicator-layer@1.0",
        len(rows),
        schema,
        rows[:20],
        "normalised_indicator_table",
        issues,
    )


DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}


def validate_document(filename: str, payload: bytes, media_type: str) -> ValidationResult:
    suffix = Path(filename).suffix.lower()
    issues: list[ValidationIssue] = []
    if suffix not in DOCUMENT_EXTENSIONS:
        issues.append(ValidationIssue("DOCUMENT_TYPE_UNSUPPORTED", "Supported document type", "BLOCKING", "Supported document types are PDF, DOCX, Markdown, and plain text.", 1))
    guessed = mimetypes.guess_type(filename)[0]
    aliases = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/pdf", "text/plain", "text/markdown", "application/octet-stream"}
    if guessed and media_type not in aliases and media_type != guessed:
        issues.append(ValidationIssue("DOCUMENT_MIME_MISMATCH", "MIME and extension", "WARNING", f"Declared MIME {media_type} differs from extension-derived {guessed}."))
    return ValidationResult(
        "document@1.0",
        1,
        {"format": suffix.lstrip("."), "media_type": media_type, "size_bytes": len(payload)},
        None,
        "document_metadata",
        issues,
    )


def validate_file(profile_key: str, filename: str, payload: bytes, media_type: str) -> ValidationResult:
    if profile_key == "analysis-ready-priority-bundle@1.0":
        return validate_analysis_bundle(filename, payload)
    if profile_key == "generic-vector@1.0":
        return validate_generic_vector(filename, payload)
    if profile_key == "generic-table@1.0":
        return validate_generic_table(filename, payload)
    if profile_key == "administrative-boundary@1.0":
        return validate_administrative_boundary(filename, payload)
    if profile_key == "normalised-indicator-layer@1.0":
        return validate_normalised_indicator_layer(filename, payload)
    if profile_key == "document@1.0":
        return validate_document(filename, payload, media_type)
    raise ValueError(f"Unsupported validation profile: {profile_key}")
