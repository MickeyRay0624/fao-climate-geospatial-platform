from __future__ import annotations

import csv
import io
import json
import mimetypes
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from shapely.geometry import mapping, shape
from shapely.wkb import loads as load_wkb

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
    derived_payload: bytes | None = None
    derived_filename: str | None = None
    derived_media_type: str | None = None

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


VECTOR_FEATURE_LIMIT = 50_000
VECTOR_PREVIEW_LIMIT = 2_000
ZIP_FILE_LIMIT = 64
ZIP_UNCOMPRESSED_LIMIT = 512 * 1024 * 1024
ZIP_COMPRESSION_RATIO_LIMIT = 200


def _epsg_from_wkt(value: str) -> int | None:
    authorities = re.findall(
        r'AUTHORITY\s*\[\s*["\']EPSG["\']\s*,\s*["\'](\d+)["\']\s*\]',
        value,
        flags=re.IGNORECASE,
    )
    if authorities:
        return int(authorities[-1])
    normalised = value.upper().replace("_", " ")
    if "WGS 84" in normalised or "WGS1984" in normalised or "WGS 1984" in normalised:
        return 4326
    return None


def _json_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def _direct_vector_result(
    *,
    filename: str,
    format_name: str,
    layer_name: str,
    source_epsg: int | None,
    fields: list[dict[str, Any]],
    features: list[dict[str, Any]],
    declared_count: int,
    issues: list[ValidationIssue],
) -> ValidationResult:
    safe_source = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip("-.") or "source"
    safe_layer = re.sub(r"[^A-Za-z0-9._-]+", "-", layer_name).strip("-.") or "layer"
    invalid = 0
    bounds: list[tuple[float, float, float, float]] = []
    geometry_types: set[str] = set()
    valid_features: list[dict[str, Any]] = []
    for feature in features:
        raw_geometry = feature.get("geometry")
        try:
            geometry = shape(raw_geometry) if raw_geometry else None
            if geometry is None or geometry.is_empty or not geometry.is_valid:
                invalid += 1
                continue
            geometry_types.add(geometry.geom_type)
            bounds.append(geometry.bounds)
            valid_features.append(feature)
        except Exception:
            invalid += 1
    if invalid:
        issues.append(
            ValidationIssue(
                "VECTOR_INVALID_GEOMETRY",
                "Valid geometry",
                "BLOCKING",
                f"{invalid} features have missing or invalid geometry.",
                invalid,
            )
        )
    if declared_count > VECTOR_FEATURE_LIMIT:
        issues.append(
            ValidationIssue(
                "VECTOR_FEATURE_LIMIT",
                "Demonstration ingestion feature limit",
                "BLOCKING",
                f"The layer has {declared_count} features; this local path is limited to {VECTOR_FEATURE_LIMIT}.",
                declared_count,
            )
        )
    if source_epsg is None:
        issues.append(
            ValidationIssue(
                "VECTOR_CRS_UNRESOLVED",
                "Declared coordinate reference system",
                "BLOCKING",
                "The source CRS could not be resolved to an EPSG identifier.",
                1,
            )
        )
    elif source_epsg != 4326:
        issues.append(
            ValidationIssue(
                "VECTOR_PREVIEW_REPROJECTION_REQUIRED",
                "Explicit preview reprojection",
                "BLOCKING",
                f"Source EPSG:{source_epsg} is preserved, but this local preview path only derives EPSG:4326 without silent reprojection.",
                1,
                {"source_crs": f"EPSG:{source_epsg}", "target_crs": "EPSG:4326"},
            )
        )
    bbox = None
    if bounds:
        bbox = [
            min(item[0] for item in bounds),
            min(item[1] for item in bounds),
            max(item[2] for item in bounds),
            max(item[3] for item in bounds),
        ]
    preview_features = valid_features[:VECTOR_PREVIEW_LIMIT]
    preview = {"type": "FeatureCollection", "features": preview_features}
    blocking = any(issue.severity == "BLOCKING" for issue in issues)
    derived = None
    if not blocking:
        derived = json.dumps(
            {"type": "FeatureCollection", "features": valid_features},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    schema = {
        "format": format_name,
        "source_filename": filename,
        "layer": layer_name,
        "fields": fields,
        "record_count": declared_count,
        "geometry_types": sorted(geometry_types),
        "source_crs": f"EPSG:{source_epsg}" if source_epsg else None,
        "preview_crs": "EPSG:4326" if source_epsg == 4326 else None,
        "preview_feature_count": len(preview_features),
        "preview_display_cap": VECTOR_PREVIEW_LIMIT,
        "source_preserved": True,
        "reprojected": False,
    }
    return ValidationResult(
        "generic-vector@1.0",
        declared_count,
        schema,
        preview,
        "derived_geojson_preview",
        issues,
        bbox=bbox,
        crs=f"EPSG:{source_epsg}" if source_epsg else None,
        geometry_type=",".join(sorted(geometry_types)) or None,
        derived_payload=derived,
        derived_filename=f"{safe_source}-{safe_layer}.geojson",
        derived_media_type="application/geo+json",
    )


def validate_shapefile_zip(filename: str, payload: bytes) -> ValidationResult:
    issues: list[ValidationIssue] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as error:
        return ValidationResult(
            "generic-vector@1.0",
            0,
            {"format": "Shapefile ZIP"},
            None,
            "derived_geojson_preview",
            [
                ValidationIssue(
                    "SHAPEFILE_ZIP_INVALID",
                    "Valid ZIP archive",
                    "BLOCKING",
                    str(error),
                    1,
                )
            ],
        )
    with archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        if len(entries) > ZIP_FILE_LIMIT:
            issues.append(
                ValidationIssue(
                    "VECTOR_ZIP_FILE_LIMIT",
                    "Controlled archive file count",
                    "BLOCKING",
                    f"Archive contains {len(entries)} files; maximum is {ZIP_FILE_LIMIT}.",
                    len(entries),
                )
            )
        total_size = sum(entry.file_size for entry in entries)
        if total_size > ZIP_UNCOMPRESSED_LIMIT:
            issues.append(
                ValidationIssue(
                    "VECTOR_ZIP_UNCOMPRESSED_LIMIT",
                    "Controlled uncompressed size",
                    "BLOCKING",
                    f"Archive expands to {total_size} bytes; maximum is {ZIP_UNCOMPRESSED_LIMIT}.",
                    total_size,
                )
            )
        unsafe = []
        bomb_entries = []
        nested_archives = []
        by_stem: dict[str, dict[str, zipfile.ZipInfo]] = {}
        for entry in entries:
            raw_name = entry.filename
            path = PurePosixPath(raw_name)
            if (
                "\\" in raw_name
                or path.is_absolute()
                or ".." in path.parts
                or any(part in {"", "."} for part in path.parts)
            ):
                unsafe.append(raw_name)
                continue
            suffix = path.suffix.lower()
            if suffix in {".zip", ".7z", ".rar", ".tar", ".gz"}:
                nested_archives.append(raw_name)
            if entry.file_size and (
                entry.compress_size == 0
                or entry.file_size / max(entry.compress_size, 1)
                > ZIP_COMPRESSION_RATIO_LIMIT
            ):
                bomb_entries.append(raw_name)
            by_stem.setdefault(str(path.with_suffix("")).lower(), {})[suffix] = entry
        if unsafe:
            issues.append(
                ValidationIssue(
                    "VECTOR_ZIP_UNSAFE_PATH",
                    "Archive path safety",
                    "BLOCKING",
                    "Unsafe absolute, traversal or ambiguous paths were rejected.",
                    len(unsafe),
                    {"entries": unsafe[:10]},
                )
            )
        if bomb_entries:
            issues.append(
                ValidationIssue(
                    "VECTOR_ZIP_COMPRESSION_RATIO",
                    "Compression bomb protection",
                    "BLOCKING",
                    "One or more entries exceed the allowed compression ratio.",
                    len(bomb_entries),
                    {"entries": bomb_entries[:10]},
                )
            )
        if nested_archives:
            issues.append(
                ValidationIssue(
                    "VECTOR_ZIP_NESTED_ARCHIVE",
                    "No nested archives",
                    "BLOCKING",
                    "Nested archives are not processed.",
                    len(nested_archives),
                    {"entries": nested_archives[:10]},
                )
            )
        required = {".shp", ".shx", ".dbf", ".prj"}
        complete = [stem for stem, values in by_stem.items() if required <= values.keys()]
        if not complete:
            candidates = [
                {
                    "layer": stem,
                    "missing": sorted(required - values.keys()),
                }
                for stem, values in by_stem.items()
                if values.keys() & {".shp", ".shx", ".dbf"}
            ]
            issues.append(
                ValidationIssue(
                    "SHAPEFILE_COMPONENTS_MISSING",
                    "Complete Shapefile components",
                    "BLOCKING",
                    "A single layer must include matching .shp, .shx, .dbf and .prj files.",
                    max(1, len(candidates)),
                    {"layers": candidates[:10]},
                )
            )
        if len(complete) > 1:
            issues.append(
                ValidationIssue(
                    "VECTOR_LAYER_SELECTION_REQUIRED",
                    "Single layer selection",
                    "BLOCKING",
                    "The archive contains multiple complete layers; select one in a future layer-selection step.",
                    len(complete),
                    {"layers": complete},
                )
            )
        if any(issue.severity == "BLOCKING" for issue in issues) or len(complete) != 1:
            return ValidationResult(
                "generic-vector@1.0",
                0,
                {
                    "format": "Shapefile ZIP",
                    "archive_file_count": len(entries),
                    "uncompressed_size_bytes": total_size,
                    "layers": complete,
                },
                None,
                "derived_geojson_preview",
                issues,
            )
        stem = complete[0]
        values = by_stem[stem]
        try:
            import shapefile

            encoding = "utf-8"
            if ".cpg" in values:
                encoding = archive.read(values[".cpg"]).decode("ascii", "ignore").strip() or "utf-8"
            reader = shapefile.Reader(
                shp=io.BytesIO(archive.read(values[".shp"])),
                shx=io.BytesIO(archive.read(values[".shx"])),
                dbf=io.BytesIO(archive.read(values[".dbf"])),
                encoding=encoding,
            )
            count = len(reader)
            if count > VECTOR_FEATURE_LIMIT:
                features: list[dict[str, Any]] = []
            else:
                features = [
                    {
                        "type": "Feature",
                        "id": str(index + 1),
                        "properties": {
                            key: _json_scalar(value)
                            for key, value in record.record.as_dict().items()
                        },
                        "geometry": record.shape.__geo_interface__,
                    }
                    for index, record in enumerate(reader.iterShapeRecords())
                ]
            fields = [
                {"name": item[0], "type": item[1], "width": item[2], "decimals": item[3]}
                for item in reader.fields[1:]
            ]
            prj = archive.read(values[".prj"]).decode("utf-8", "ignore")
            epsg = _epsg_from_wkt(prj)
            return _direct_vector_result(
                filename=filename,
                format_name="Shapefile ZIP",
                layer_name=PurePosixPath(stem).name,
                source_epsg=epsg,
                fields=fields,
                features=features,
                declared_count=count,
                issues=issues,
            )
        except Exception as error:
            issues.append(
                ValidationIssue(
                    "SHAPEFILE_NOT_PARSEABLE",
                    "Parseable Shapefile",
                    "BLOCKING",
                    str(error),
                    1,
                )
            )
            return ValidationResult(
                "generic-vector@1.0",
                0,
                {"format": "Shapefile ZIP", "layer": stem},
                None,
                "derived_geojson_preview",
                issues,
            )


def _gpkg_geometry(value: Any):
    payload = bytes(value)
    if len(payload) < 8 or payload[:2] != b"GP":
        raise ValueError("Invalid GeoPackage geometry header")
    flags = payload[3]
    if flags & 0x10:
        return None
    envelope_size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((flags >> 1) & 0x07)
    if envelope_size is None:
        raise ValueError("Unsupported GeoPackage geometry envelope")
    return load_wkb(payload[8 + envelope_size :])


def _quote_sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def validate_geopackage(filename: str, payload: bytes) -> ValidationResult:
    issues: list[ValidationIssue] = []
    if not payload.startswith(b"SQLite format 3\x00"):
        issues.append(
            ValidationIssue(
                "GEOPACKAGE_SIGNATURE_INVALID",
                "Valid GeoPackage container",
                "BLOCKING",
                "The file is not a SQLite/GeoPackage container.",
                1,
            )
        )
        return ValidationResult(
            "generic-vector@1.0", 0, {"format": "GeoPackage"}, None,
            "derived_geojson_preview", issues,
        )
    try:
        with tempfile.NamedTemporaryFile(suffix=".gpkg") as temporary:
            temporary.write(payload)
            temporary.flush()
            connection = sqlite3.connect(f"file:{temporary.name}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA query_only = ON")
                connection.execute("PRAGMA trusted_schema = OFF")
                layers = connection.execute(
                    """
                    SELECT c.table_name, c.identifier, g.column_name, g.srs_id
                    FROM gpkg_contents c
                    JOIN gpkg_geometry_columns g ON g.table_name = c.table_name
                    WHERE c.data_type = 'features'
                    ORDER BY c.table_name
                    """
                ).fetchall()
                if not layers:
                    issues.append(
                        ValidationIssue(
                            "GEOPACKAGE_FEATURE_LAYER_MISSING",
                            "GeoPackage feature layer",
                            "BLOCKING",
                            "No vector feature layer was found.",
                            1,
                        )
                    )
                if len(layers) > 1:
                    issues.append(
                        ValidationIssue(
                            "VECTOR_LAYER_SELECTION_REQUIRED",
                            "Single layer selection",
                            "BLOCKING",
                            "The GeoPackage contains multiple feature layers; select one in a future layer-selection step.",
                            len(layers),
                            {"layers": [row["table_name"] for row in layers]},
                        )
                    )
                if len(layers) != 1:
                    return ValidationResult(
                        "generic-vector@1.0",
                        0,
                        {"format": "GeoPackage", "layers": [row["table_name"] for row in layers]},
                        None,
                        "derived_geojson_preview",
                        issues,
                    )
                layer = layers[0]
                table_name = layer["table_name"]
                geometry_column = layer["column_name"]
                quoted_table = _quote_sqlite_identifier(table_name)
                columns = connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
                fields = [
                    {"name": row["name"], "type": row["type"], "nullable": not bool(row["notnull"])}
                    for row in columns
                    if row["name"] != geometry_column
                ]
                primary_key = next((row["name"] for row in columns if row["pk"]), None)
                count = int(
                    connection.execute(f"SELECT count(*) FROM {quoted_table}").fetchone()[0]
                )
                srs = connection.execute(
                    "SELECT organization, organization_coordsys_id FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
                    (layer["srs_id"],),
                ).fetchone()
                epsg = (
                    int(srs["organization_coordsys_id"])
                    if srs and str(srs["organization"]).upper() == "EPSG"
                    else None
                )
                features: list[dict[str, Any]] = []
                if count <= VECTOR_FEATURE_LIMIT:
                    selected_columns = ", ".join(
                        _quote_sqlite_identifier(row["name"]) for row in columns
                    )
                    rows = connection.execute(
                        f"SELECT {selected_columns} FROM {quoted_table}"
                    )
                    for index, row in enumerate(rows):
                        geometry = _gpkg_geometry(row[geometry_column]) if row[geometry_column] is not None else None
                        features.append(
                            {
                                "type": "Feature",
                                "id": str(row[primary_key]) if primary_key else str(index + 1),
                                "properties": {
                                    key: _json_scalar(row[key])
                                    for key in row.keys()
                                    if key != geometry_column
                                },
                                "geometry": mapping(geometry) if geometry else None,
                            }
                        )
                return _direct_vector_result(
                    filename=filename,
                    format_name="GeoPackage",
                    layer_name=table_name,
                    source_epsg=epsg,
                    fields=fields,
                    features=features,
                    declared_count=count,
                    issues=issues,
                )
            finally:
                connection.close()
    except (sqlite3.Error, OSError, ValueError) as error:
        issues.append(
            ValidationIssue(
                "GEOPACKAGE_NOT_PARSEABLE",
                "Parseable GeoPackage",
                "BLOCKING",
                str(error),
                1,
            )
        )
        return ValidationResult(
            "generic-vector@1.0", 0, {"format": "GeoPackage"}, None,
            "derived_geojson_preview", issues,
        )


def validate_generic_vector(filename: str, payload: bytes) -> ValidationResult:
    suffix = Path(filename).suffix.lower()
    if suffix == ".zip":
        return validate_shapefile_zip(filename, payload)
    if suffix == ".gpkg":
        return validate_geopackage(filename, payload)
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
