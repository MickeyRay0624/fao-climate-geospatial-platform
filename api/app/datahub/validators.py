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
    if profile_key == "document@1.0":
        return validate_document(filename, payload, media_type)
    raise ValueError(f"Unsupported validation profile: {profile_key}")
