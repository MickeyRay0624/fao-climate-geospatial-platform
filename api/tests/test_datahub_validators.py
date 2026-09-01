import io
import json
import sqlite3
import struct
import tempfile
import zipfile

import pytest
from shapely.geometry import Point
from shapely.wkb import dumps as dump_wkb

from app.datahub.validators import (
    DevelopmentBypassScanner,
    FailClosedScanner,
    validate_document,
    validate_file,
    validate_generic_table,
    validate_generic_vector,
    validate_geopackage,
    validate_shapefile_zip,
    validate_administrative_boundary,
    validate_normalised_indicator_layer,
)


def test_generic_vector_reports_preview_bbox_and_assumed_crs() -> None:
    payload = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"code": "A", "risk": 0.7},
                    "geometry": {"type": "Point", "coordinates": [104.9, 11.6]},
                }
            ],
        }
    ).encode()

    result = validate_generic_vector("points.geojson", payload)

    assert result.status == "WARNING"
    assert result.record_count == 1
    assert result.bbox == [104.9, 11.6, 104.9, 11.6]
    assert result.geometry_type == "Point"
    assert result.schema["fields"] == ["code", "risk"]
    assert result.issues[0].code == "VECTOR_CRS_ASSUMED"


def test_generic_vector_rejects_invalid_geometry() -> None:
    payload = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": None}],
        }
    ).encode()

    result = validate_generic_vector("invalid.geojson", payload)

    assert result.has_blocking is True
    assert result.status == "FAILED"
    assert {issue.code for issue in result.issues} == {"VECTOR_INVALID_GEOMETRY", "VECTOR_CRS_ASSUMED"}


def test_generic_vector_requires_feature_collection() -> None:
    result = validate_generic_vector("item.geojson", b'{"type":"Feature"}')

    assert result.status == "FAILED"
    assert result.issues[0].code == "VECTOR_NOT_FEATURE_COLLECTION"


def test_table_infers_types_and_returns_preview() -> None:
    result = validate_generic_table("sample.csv", b"code,value,name\nA,1,alpha\nB,2.5,beta\n")

    assert result.status == "PASSED"
    assert result.record_count == 2
    assert result.schema["inferred_types"]["value"] == ["integer", "number"]
    assert result.preview[0] == {"code": "A", "value": "1", "name": "alpha"}


def test_table_rejects_duplicate_columns_and_malformed_rows() -> None:
    result = validate_generic_table("bad.csv", b"code,code\nA,1\nB\n")

    assert result.status == "FAILED"
    assert {issue.code for issue in result.issues} == {"TABLE_DUPLICATE_COLUMNS", "TABLE_MALFORMED_ROWS"}


def test_document_profile_rejects_unsupported_extension() -> None:
    result = validate_document("payload.exe", b"payload", "application/octet-stream")

    assert result.status == "FAILED"
    assert result.issues[0].code == "DOCUMENT_TYPE_UNSUPPORTED"


def test_profile_dispatch_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="Unsupported validation profile"):
        validate_file("unknown@1", "sample.csv", b"a\n1", "text/csv")


def test_shapefile_zip_rejects_traversal_and_missing_components() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.shp", b"unsafe")
        archive.writestr("incomplete.dbf", b"dbf")
        archive.writestr("incomplete.prj", b"GEOGCS[\"WGS 84\"]")

    result = validate_shapefile_zip("incomplete.zip", payload.getvalue())

    assert result.status == "FAILED"
    assert {issue.code for issue in result.issues} == {
        "VECTOR_ZIP_UNSAFE_PATH",
        "SHAPEFILE_COMPONENTS_MISSING",
    }


def test_complete_wgs84_shapefile_zip_creates_derived_geojson_preview() -> None:
    import shapefile

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POINT)
    writer.field("area_code", "C", size=20)
    writer.point(104.9, 11.6)
    writer.record("KH-DEMO-01")
    writer.close()
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("demo.shp", shp.getvalue())
        archive.writestr("demo.shx", shx.getvalue())
        archive.writestr("demo.dbf", dbf.getvalue())
        archive.writestr(
            "demo.prj",
            'GEOGCS["WGS 84",DATUM["WGS_1984"],AUTHORITY["EPSG","4326"]]',
        )

    result = validate_shapefile_zip("demo.zip", payload.getvalue())

    assert result.status == "PASSED"
    assert result.record_count == 1
    assert result.crs == "EPSG:4326"
    assert result.schema["format"] == "Shapefile ZIP"
    assert result.preview["features"][0]["properties"]["area_code"] == "KH-DEMO-01"
    assert result.derived_payload is not None
    assert result.derived_media_type == "application/geo+json"


def test_single_layer_geopackage_creates_governed_preview() -> None:
    with tempfile.NamedTemporaryFile(suffix=".gpkg") as temporary:
        connection = sqlite3.connect(temporary.name)
        connection.executescript(
            """
            CREATE TABLE gpkg_spatial_ref_sys (
              srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
              organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
              definition TEXT NOT NULL, description TEXT
            );
            CREATE TABLE gpkg_contents (
              table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
              identifier TEXT, description TEXT DEFAULT '', last_change DATETIME,
              min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER
            );
            CREATE TABLE gpkg_geometry_columns (
              table_name TEXT NOT NULL, column_name TEXT NOT NULL,
              geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
              z TINYINT NOT NULL, m TINYINT NOT NULL,
              PRIMARY KEY (table_name, column_name)
            );
            CREATE TABLE demo_points (fid INTEGER PRIMARY KEY, geom BLOB, area_code TEXT);
            """
        )
        connection.execute(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)",
            ("WGS 84", 4326, "EPSG", 4326, "WGS 84", "Test fixture"),
        )
        connection.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id) VALUES (?, ?, ?, ?)",
            ("demo_points", "features", "Demo points", 4326),
        )
        connection.execute(
            "INSERT INTO gpkg_geometry_columns VALUES (?, ?, ?, ?, ?, ?)",
            ("demo_points", "geom", "POINT", 4326, 0, 0),
        )
        geometry = b"GP" + bytes([0, 1]) + struct.pack("<i", 4326) + dump_wkb(Point(104.9, 11.6))
        connection.execute(
            "INSERT INTO demo_points (geom, area_code) VALUES (?, ?)",
            (geometry, "KH-DEMO-01"),
        )
        connection.commit()
        connection.close()
        temporary.seek(0)
        payload = temporary.read()

    result = validate_geopackage("demo.gpkg", payload)

    assert result.status == "PASSED"
    assert result.record_count == 1
    assert result.schema["layer"] == "demo_points"
    assert result.preview["features"][0]["geometry"]["type"] == "Point"


def test_file_scanner_boundary_is_visibly_bypassed_or_fail_closed() -> None:
    assert DevelopmentBypassScanner().scan("sample.csv", b"data") == "BYPASSED_DEV"
    with pytest.raises(RuntimeError, match="No approved malware scanner"):
        FailClosedScanner().scan("sample.csv", b"data")


def test_native_boundary_contract_records_extent_schema_and_crs_assumption() -> None:
    payload = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "area_code": "KH-01",
                        "area_name": "Synthetic district",
                        "admin_level": "district",
                        "parent_code": "KH",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[104.0, 11.0], [104.1, 11.0], [104.1, 11.1], [104.0, 11.0]]],
                    },
                }
            ],
        }
    ).encode()

    result = validate_administrative_boundary("boundary.geojson", payload)

    assert result.status == "WARNING"
    assert result.record_count == 1
    assert result.representation_type == "administrative_boundary"
    assert result.schema["join_key"] == "area_code"
    assert result.bbox == [104.0, 11.0, 104.1, 11.1]
    assert {issue.code for issue in result.issues} == {"VECTOR_CRS_ASSUMED"}


def test_native_indicator_missing_value_warns_without_blocking() -> None:
    result = validate_normalised_indicator_layer(
        "poverty.csv",
        (
            b"area_code,value,indicator_code,unit,direction,time_start,time_end\n"
            b"KH-01,0.42,poverty_index,index,higher_is_priority,2025-01-01,2025-12-31\n"
            b"KH-02,,poverty_index,index,higher_is_priority,2025-01-01,2025-12-31\n"
        ),
    )

    assert result.status == "WARNING"
    assert result.has_blocking is False
    assert result.representation_type == "normalised_indicator_table"
    assert result.schema["indicator_code"] == "poverty_index"
    assert {issue.code for issue in result.issues} == {"INDICATOR_VALUES_MISSING"}


def test_native_indicator_duplicate_area_code_is_blocking() -> None:
    result = validate_normalised_indicator_layer(
        "poverty.csv",
        (
            b"area_code,value,indicator_code,unit,direction,time_start,time_end\n"
            b"KH-01,0.42,poverty_index,index,higher_is_priority,2025-01-01,2025-12-31\n"
            b"KH-01,0.50,poverty_index,index,higher_is_priority,2025-01-01,2025-12-31\n"
        ),
    )

    assert result.status == "FAILED"
    assert "INDICATOR_AREA_CODE_DUPLICATE" in {issue.code for issue in result.issues}
