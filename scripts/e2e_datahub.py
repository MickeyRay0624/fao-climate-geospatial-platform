#!/usr/bin/env python3
"""Exercise the complete Phase 1 Data Hub workflow against the local stack."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "api" / "tests" / "fixtures" / "datahub-e2e.geojson"
API = "http://localhost:8000"


class ApiFailure(RuntimeError):
    def __init__(self, status: int, body: dict[str, Any] | str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body

    @property
    def code(self) -> str | None:
        return self.body.get("error", {}).get("code") if isinstance(self.body, dict) else None


def call(
    method: str,
    path: str,
    *,
    persona: str = "dev-admin",
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[Any, dict[str, str]]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Dev-User-Subject": persona,
        "X-Correlation-ID": f"e2e-{uuid.uuid4()}",
    }
    if method in {"POST", "PATCH", "DELETE"}:
        headers["Idempotency-Key"] = idempotency_key or f"e2e-{uuid.uuid4()}"
    request = Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            content = response.read()
            return (json.loads(content) if content else None), {
                key.lower(): value for key, value in response.headers.items()
            }
    except HTTPError as error:
        content = error.read()
        try:
            body = json.loads(content)
        except json.JSONDecodeError:
            body = content.decode(errors="replace")
        raise ApiFailure(error.code, body) from error


def expect_denied(
    method: str,
    path: str,
    persona: str,
    expected_status: int,
    expected_code: str,
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        call(method, path, persona=persona, payload=payload if method == "POST" else None)
    except ApiFailure as error:
        assert error.status == expected_status, error
        assert error.code == expected_code, error
        return
    raise AssertionError(f"{persona} unexpectedly accessed {path}")


def main() -> int:
    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    payload_bytes = FIXTURE.read_bytes()
    media_type = mimetypes.guess_type(FIXTURE.name)[0] or "application/geo+json"
    report: dict[str, Any] = {"run_tag": run_tag, "checks": []}

    health, _ = call("GET", "/health")
    assert health["database"] == health["object_storage"] == health["redis"] == health["worker"] == "ok"
    report["checks"].append("dependencies healthy")

    personas, _ = call("GET", "/api/dev/personas")
    viewer = next(item for item in personas["items"] if item["external_subject"] == "dev-viewer")

    create_key = f"e2e-create-{uuid.uuid4()}"
    dataset_body = {
        "title": f"Phase 1 workflow verification {run_tag}",
        "slug": f"phase-1-workflow-verification-{run_tag}",
        "abstract": "A two-feature synthetic GeoJSON used to verify the governed Phase 1 lifecycle end to end.",
        "data_kind": "vector",
        "visibility": "PRIVATE",
        "classification": "FAO_INTERNAL",
        "licence_code": "FAO-PILOT",
    }
    dataset, response_headers = call("POST", "/api/data/v1/datasets", persona="dev-contributor", payload=dataset_body, idempotency_key=create_key)
    replay, _ = call("POST", "/api/data/v1/datasets", persona="dev-contributor", payload=dataset_body, idempotency_key=create_key)
    assert replay["id"] == dataset["id"]
    assert response_headers.get("x-correlation-id")
    report["checks"].append("idempotent dataset registration and correlation ID")

    version, _ = call(
        "POST",
        f"/api/data/v1/datasets/{dataset['id']}/versions",
        persona="dev-contributor",
        payload={
            "version_label": "1.0.0",
            "profile_key": "generic-vector@1.0",
            "change_summary": "Initial Phase 1 end-to-end verification release",
            "metadata": {
                "title": dataset_body["title"],
                "abstract": dataset_body["abstract"],
                "purpose": "Verify direct upload, validation, review, publication and controlled access.",
                "producer": "FAO Climate Change Group local pilot",
                "provenance": "Deterministic local fixture created for Phase 1 workflow verification.",
                "licence_code": "FAO-PILOT",
                "use_limitation": "Synthetic verification points; not for operational use or agronomic advice.",
                "crs": "EPSG:4326",
                "methodology": "Two static points encoded as RFC 7946 GeoJSON.",
                "quality_statement": "Validated by generic-vector@1.0.",
                "keywords": ["synthetic", "verification", "Cambodia"],
                "language": "en",
                "sensitive_data_declaration": "No sensitive data; synthetic points only.",
                "citation": "FAO Climate Platform Phase 1 local verification fixture",
                "source_url": None,
            },
        },
    )

    upload, _ = call(
        "POST",
        f"/api/data/v1/versions/{version['id']}/upload-sessions",
        persona="dev-contributor",
        payload={
            "files": [{
                "filename": FIXTURE.name,
                "media_type": media_type,
                "size_bytes": len(payload_bytes),
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
            }]
        },
    )
    put_request = Request(
        upload["files"][0]["upload_url"],
        data=payload_bytes,
        method="PUT",
        headers={"Content-Type": media_type},
    )
    with urlopen(put_request, timeout=15) as response:
        assert response.status in {200, 201}
    job, _ = call("POST", f"/api/data/v1/upload-sessions/{upload['id']}/complete", persona="dev-contributor", payload={})
    for _ in range(60):
        job, _ = call("GET", f"/api/jobs/v1/jobs/{job['id']}", persona="dev-contributor")
        if job["status"] not in {"QUEUED", "RUNNING"}:
            break
        time.sleep(0.5)
    assert job["status"] == "SUCCEEDED", job
    assert [item["status"] for item in job["steps"]] == ["SUCCEEDED"] * 4
    version, _ = call("GET", f"/api/data/v1/versions/{version['id']}", persona="dev-contributor")
    assert version["state"] == "VALIDATED"
    assert version["assets"][0]["scan_status"] == "BYPASSED_DEV"
    report["checks"].append("direct quarantine upload, checksum, visible scan bypass and background validation")

    review_key = f"e2e-review-{uuid.uuid4()}"
    review, _ = call(
        "POST",
        f"/api/data/v1/versions/{version['id']}/submit-review",
        persona="dev-contributor",
        payload={"review_type": "publication", "row_version": version["row_version"]},
        idempotency_key=review_key,
    )
    review_replay, _ = call(
        "POST",
        f"/api/data/v1/versions/{version['id']}/submit-review",
        persona="dev-contributor",
        payload={"review_type": "publication", "row_version": version["row_version"]},
        idempotency_key=review_key,
    )
    assert review_replay["id"] == review["id"]
    expect_denied(
        "POST",
        f"/api/data/v1/versions/{version['id']}/publish",
        "dev-reviewer",
        403,
        "FORBIDDEN",
        {"row_version": version["row_version"], "exception_reason": None},
    )
    reviewer_version, _ = call("GET", f"/api/data/v1/versions/{version['id']}", persona="dev-reviewer")
    assert reviewer_version["state"] == "IN_REVIEW"
    decision_key = f"e2e-decision-{uuid.uuid4()}"
    decision_body = {
        "decision": "APPROVE",
        "rationale": "Metadata, provenance, source checksum, preview and structured quality evidence verified.",
        "checklist_snapshot": {"metadata": True, "provenance": True, "quality": True, "preview": True},
    }
    decision, _ = call(
        "POST",
        f"/api/data/v1/reviews/{review['id']}/decisions",
        persona="dev-reviewer",
        payload=decision_body,
        idempotency_key=decision_key,
    )
    decision_replay, _ = call(
        "POST",
        f"/api/data/v1/reviews/{review['id']}/decisions",
        persona="dev-reviewer",
        payload=decision_body,
        idempotency_key=decision_key,
    )
    assert decision_replay["id"] == decision["id"]
    assert decision["version_state"] == "APPROVED"
    report["checks"].append("idempotent scoped review and reviewer/publisher separation")

    approved, _ = call("GET", f"/api/data/v1/versions/{version['id']}", persona="dev-publisher")
    published, _ = call(
        "POST",
        f"/api/data/v1/versions/{version['id']}/publish",
        persona="dev-publisher",
        payload={"row_version": approved["row_version"], "exception_reason": None},
    )
    assert published["state"] == "PUBLISHED"
    assert published["metadata_snapshot"]["title"] == dataset_body["title"]
    report["checks"].append("publisher gate and immutable metadata snapshot")

    expect_denied("GET", f"/api/data/v1/versions/{version['id']}", "dev-viewer", 404, "RESOURCE_NOT_FOUND")
    grant_ids: list[str] = []
    for permission in ["dataset.view_metadata", "dataset.preview", "dataset.download", "lineage.view"]:
        grant_key = f"e2e-grant-{permission}-{uuid.uuid4()}"
        grant_body = {
            "subject_type": "user",
            "subject_id": viewer["id"],
            "permission_code": permission,
            "effect": "ALLOW",
            "expires_at": None,
            "reason": "Phase 1 controlled-access verification grant.",
        }
        grant, _ = call(
            "POST",
            f"/api/data/v1/datasets/{dataset['id']}/grants",
            persona="dev-contributor",
            payload=grant_body,
            idempotency_key=grant_key,
        )
        grant_replay, _ = call(
            "POST",
            f"/api/data/v1/datasets/{dataset['id']}/grants",
            persona="dev-contributor",
            payload=grant_body,
            idempotency_key=grant_key,
        )
        assert grant_replay["id"] == grant["id"]
        grant_ids.append(grant["id"])
    preview, _ = call("GET", f"/api/data/v1/versions/{version['id']}/preview", persona="dev-viewer")
    assert len(preview["preview"]["features"]) == 2
    download, _ = call("GET", f"/api/data/v1/versions/{version['id']}/download", persona="dev-viewer")
    with urlopen(download["url"], timeout=15) as response:
        assert hashlib.sha256(response.read()).hexdigest() == hashlib.sha256(payload_bytes).hexdigest()
    report["checks"].append("private non-disclosure, explicit grants, audited preview and signed download")

    deny, _ = call(
        "POST",
        f"/api/data/v1/datasets/{dataset['id']}/grants",
        persona="dev-contributor",
        payload={
            "subject_type": "user",
            "subject_id": viewer["id"],
            "permission_code": "dataset.download",
            "effect": "DENY",
            "expires_at": None,
            "reason": "Verify explicit deny precedence over an allow grant.",
        },
    )
    expect_denied("GET", f"/api/data/v1/versions/{version['id']}/download", "dev-viewer", 404, "RESOURCE_NOT_FOUND")
    delete_key = f"e2e-delete-grant-{uuid.uuid4()}"
    deleted, _ = call(
        "DELETE",
        f"/api/data/v1/datasets/{dataset['id']}/grants/{deny['id']}",
        persona="dev-contributor",
        idempotency_key=delete_key,
    )
    delete_replay, _ = call(
        "DELETE",
        f"/api/data/v1/datasets/{dataset['id']}/grants/{deny['id']}",
        persona="dev-contributor",
        idempotency_key=delete_key,
    )
    assert deleted == delete_replay
    restored, _ = call("GET", f"/api/data/v1/versions/{version['id']}/download", persona="dev-viewer")
    assert restored["filename"] == FIXTURE.name
    report["checks"].append("explicit DENY precedence and recoverable grant removal")

    lineage, _ = call("GET", f"/api/data/v1/versions/{version['id']}/lineage", persona="dev-viewer")
    assert lineage["processes"][0]["method_identifier"] == "generic-vector@1.0"
    audit, _ = call("GET", f"/api/audit/v1/events?resource_id={version['id']}&page_size=100", persona="dev-auditor")
    actions = {item["action"] for item in audit["items"]}
    assert {"catalog.version.create", "catalog.version.processing.complete", "catalog.version.publish", "catalog.version.preview", "catalog.asset.download"} <= actions
    report["checks"].append("version lineage and append-only lifecycle audit evidence")

    report.update({
        "status": "passed",
        "dataset_id": dataset["id"],
        "version_id": version["id"],
        "job_id": job["id"],
        "review_id": review["id"],
        "quality_status": published["quality"]["status"],
        "asset_sha256": published["assets"][0]["sha256"],
        "viewer_allow_grants": grant_ids,
    })
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"E2E FAILED: {error}", file=sys.stderr)
        raise
