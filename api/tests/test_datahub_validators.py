import json

import pytest

from app.datahub.validators import (
    DevelopmentBypassScanner,
    FailClosedScanner,
    validate_document,
    validate_file,
    validate_generic_table,
    validate_generic_vector,
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
