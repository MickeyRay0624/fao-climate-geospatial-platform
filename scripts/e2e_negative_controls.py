#!/usr/bin/env python3
"""Verify negative security/lifecycle paths, then archive the test resource."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from e2e_datahub import ApiFailure, FIXTURE, call


def expect_failure(
    method: str,
    path: str,
    *,
    persona: str,
    status: int,
    code: str,
    payload: dict | None = None,
) -> None:
    try:
        call(method, path, persona=persona, payload=payload)
    except ApiFailure as error:
        assert error.status == status, error
        assert error.code == code, error
        return
    raise AssertionError(f"Expected {status} {code}: {persona} {method} {path}")


def main() -> int:
    tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    source = FIXTURE.read_bytes()
    report = {"run_tag": tag, "checks": []}
    body = {
        "title": f"Archived negative-control lifecycle {tag}",
        "slug": f"archived-negative-control-{tag}",
        "abstract": "Temporary synthetic resource used to verify negative lifecycle and authorization controls.",
        "data_kind": "vector",
        "visibility": "PRIVATE",
        "classification": "FAO_INTERNAL",
        "licence_code": "FAO-PILOT",
    }
    dataset, _ = call("POST", "/api/data/v1/datasets", persona="dev-admin", payload=body)
    expect_failure("POST", "/api/data/v1/datasets", persona="dev-admin", status=409, code="DATASET_SLUG_CONFLICT", payload=body)
    report["checks"].append("duplicate workspace slug rejected")

    version, _ = call(
        "POST",
        f"/api/data/v1/datasets/{dataset['id']}/versions",
        persona="dev-admin",
        payload={
            "version_label": "1.0.0",
            "profile_key": "generic-vector@1.0",
            "change_summary": "Disposable negative-control release",
            "metadata": {
                "title": body["title"], "abstract": body["abstract"],
                "purpose": "Exercise guarded transitions.", "producer": "Local verification harness",
                "provenance": "Deterministic synthetic fixture.", "licence_code": "FAO-PILOT",
                "use_limitation": "Verification only; not operational data.", "crs": "EPSG:4326",
                "methodology": "Static local GeoJSON.", "quality_statement": "Automated profile.",
                "keywords": ["negative-control"], "language": "en",
                "sensitive_data_declaration": "None; synthetic.", "citation": "", "source_url": None,
            },
        },
    )
    expect_failure(
        "POST", f"/api/data/v1/versions/{version['id']}/publish",
        persona="dev-publisher", status=409, code="INVALID_VERSION_TRANSITION",
        payload={"row_version": version["row_version"], "exception_reason": None},
    )
    report["checks"].append("publisher cannot publish unfinished version")

    upload, _ = call(
        "POST", f"/api/data/v1/versions/{version['id']}/upload-sessions",
        persona="dev-admin",
        payload={"files": [{
            "filename": FIXTURE.name, "media_type": "application/geo+json",
            "size_bytes": len(source), "sha256": hashlib.sha256(source).hexdigest(),
        }]},
    )
    expect_failure(
        "POST", f"/api/data/v1/upload-sessions/{upload['id']}/complete",
        persona="dev-admin", status=409, code="UPLOAD_OBJECT_MISSING", payload={},
    )
    report["checks"].append("upload completion rejects missing quarantine object")

    with urlopen(Request(upload["files"][0]["upload_url"], data=source, method="PUT", headers={"Content-Type": "application/geo+json"}), timeout=15) as response:
        assert response.status in {200, 201}
    job, _ = call("POST", f"/api/data/v1/upload-sessions/{upload['id']}/complete", persona="dev-admin", payload={})
    replay, _ = call("POST", f"/api/data/v1/upload-sessions/{upload['id']}/complete", persona="dev-admin", payload={})
    assert replay["id"] == job["id"]
    for _ in range(60):
        job, _ = call("GET", f"/api/jobs/v1/jobs/{job['id']}", persona="dev-admin")
        if job["status"] not in {"QUEUED", "RUNNING"}:
            break
        time.sleep(0.5)
    assert job["status"] == "SUCCEEDED", job
    report["checks"].append("duplicate completion is idempotent")

    expect_failure(
        "POST", f"/api/jobs/v1/jobs/{job['id']}/retry", persona="dev-admin",
        status=409, code="JOB_NOT_RETRYABLE", payload={"reason": "Succeeded jobs must not retry."},
    )
    version, _ = call("GET", f"/api/data/v1/versions/{version['id']}", persona="dev-admin")
    review, _ = call(
        "POST", f"/api/data/v1/versions/{version['id']}/submit-review",
        persona="dev-admin", payload={"review_type": "publication", "row_version": version["row_version"]},
    )
    decision_body = {
        "decision": "APPROVE", "rationale": "Negative-control evidence checked.",
        "checklist_snapshot": {"metadata": True, "quality": True}, "exception_reason": None,
    }
    expect_failure(
        "POST", f"/api/data/v1/reviews/{review['id']}/decisions", persona="dev-admin",
        status=409, code="SEPARATION_OF_DUTIES", payload=decision_body,
    )
    decision_body["exception_reason"] = "Local pilot negative-control explicitly exercises the audited exception path."
    approved, _ = call("POST", f"/api/data/v1/reviews/{review['id']}/decisions", persona="dev-admin", payload=decision_body)
    assert approved["version_state"] == "APPROVED"
    report["checks"].append("creator cannot be sole reviewer without an audited exception")

    approved_version, _ = call("GET", f"/api/data/v1/versions/{version['id']}", persona="dev-admin")
    expect_failure(
        "POST", f"/api/data/v1/versions/{version['id']}/publish", persona="dev-admin",
        status=409, code="SEPARATION_OF_DUTIES",
        payload={"row_version": approved_version["row_version"], "exception_reason": None},
    )
    published, _ = call(
        "POST", f"/api/data/v1/versions/{version['id']}/publish", persona="dev-admin",
        payload={
            "row_version": approved_version["row_version"],
            "exception_reason": "Local pilot negative-control explicitly exercises the audited exception path.",
        },
    )
    expect_failure(
        "PATCH", f"/api/data/v1/versions/{version['id']}", persona="dev-admin",
        status=409, code="DATASET_VERSION_IMMUTABLE",
        payload={"row_version": published["row_version"], "change_summary": "tamper"},
    )
    report["checks"].append("published API representation is immutable")

    expect_failure(
        "PATCH", f"/api/data/v1/datasets/{dataset['id']}", persona="dev-viewer",
        status=404, code="RESOURCE_NOT_FOUND",
        payload={"row_version": dataset["row_version"], "title": "unauthorised edit"},
    )
    expect_failure("GET", "/api/audit/v1/events", persona="dev-viewer", status=403, code="FORBIDDEN")
    auditor_events, _ = call("GET", f"/api/audit/v1/events?resource_id={version['id']}", persona="dev-auditor")
    assert auditor_events["meta"]["total"] > 0
    report["checks"].append("viewer edit/audit denied; auditor scope succeeds")

    published, _ = call("GET", f"/api/data/v1/versions/{version['id']}", persona="dev-admin")
    deprecated, _ = call(
        "POST", f"/api/data/v1/versions/{version['id']}/deprecate", persona="dev-admin",
        payload={"row_version": published["row_version"], "reason": "Negative-control lifecycle completed."},
    )
    assert deprecated["state"] == "DEPRECATED"
    refreshed_dataset, _ = call("GET", f"/api/data/v1/datasets/{dataset['id']}", persona="dev-admin")
    archived, _ = call(
        "POST", f"/api/data/v1/datasets/{dataset['id']}/archive", persona="dev-admin",
        payload={"row_version": refreshed_dataset["row_version"], "reason": "Retain negative-control evidence outside the active catalogue."},
    )
    assert archived["lifecycle_status"] == "ARCHIVED"
    report["checks"].append("deprecate and archive lifecycle retains evidence")

    report.update({"status": "passed", "archived_dataset_id": dataset["id"], "version_id": version["id"], "job_id": job["id"]})
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
