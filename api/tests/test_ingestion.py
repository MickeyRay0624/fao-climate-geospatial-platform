import json
from pathlib import Path

from app.ingestion import parse_upload


FIXTURE = Path(__file__).parent / "fixtures" / "analysis-bundle.geojson"


def test_valid_geojson_analysis_bundle() -> None:
    parsed = parse_upload(FIXTURE.name, FIXTURE.read_bytes())

    assert parsed.has_failures is False
    assert len(parsed.records) == 2
    assert parsed.schema_summary["crs"] == "EPSG:4326"
    assert all(check.status != "failed" for check in parsed.checks)


def test_duplicate_and_out_of_range_values_fail_quality_checks() -> None:
    document = json.loads(FIXTURE.read_text())
    document["features"][1]["properties"]["code"] = "UPLOAD-001"
    document["features"][1]["properties"]["drought_risk"] = 1.4

    parsed = parse_upload("invalid.geojson", json.dumps(document).encode())
    check_status = {check.code: check.status for check in parsed.checks}

    assert parsed.has_failures is True
    assert check_status["unique_codes"] == "failed"
    assert check_status["indicator_ranges"] == "failed"


def test_unsupported_file_is_retained_as_failed_draft() -> None:
    parsed = parse_upload("notes.txt", b"not a dataset")

    assert parsed.has_failures is True
    assert parsed.records == []
    assert parsed.checks[0].code == "file_format"

