#!/usr/bin/env python3
"""Read-only smoke check for the complete local demonstration state."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


API = os.environ.get("DEMO_API_URL", "http://localhost:8000").rstrip("/")
SOURCE_SHA256 = "c30bb60f2f45ae9374578e25760a46f00257f45766bf5640c67d1cd23a34df9b"
RESULT_SHA256 = "741279cd97aed25f568c4dd8fc02cda6877acf3f65efe922af5d361db1841f54"


def get(path: str, subject: str = "dev-admin") -> Any:
    request = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Accept": "application/json",
            "X-Dev-User-Subject": subject,
            "X-Correlation-ID": "demo-smoke-read-only",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        raise RuntimeError(f"GET {path} failed with HTTP {error.code}: {body}") from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def find_title(items: list[dict[str, Any]], text: str) -> dict[str, Any]:
    try:
        return next(item for item in items if text.lower() in item.get("title", "").lower())
    except StopIteration as error:
        raise AssertionError(f"Required catalogue item containing {text!r} was not found") from error


def main() -> int:
    report: dict[str, Any] = {"status": "passed", "api": API, "checks": {}}

    health = get("/health")
    for dependency in ("database", "object_storage", "redis", "worker"):
        require(health.get(dependency) == "ok", f"Health dependency {dependency} is not ok")
    report["checks"]["dependencies"] = "healthy_with_warnings" if health.get("warnings") else "healthy"

    versions = get("/api/data-versions/available", "dev-viewer")
    legacy = next((item for item in versions if item.get("id") == 1), None)
    require(legacy is not None, "Preserved legacy dataset version 1 is missing")
    require(legacy.get("record_count") == 111, "Legacy record count changed")
    require(legacy.get("checksum_sha256") == SOURCE_SHA256, "Legacy source checksum changed")
    areas = get("/api/areas?dataset_version_id=1", "dev-viewer")
    require(len(areas.get("features", [])) == 111, "Legacy area count changed")
    report["checks"]["legacy"] = {"areas": 111, "source_sha256": SOURCE_SHA256}

    catalogue = get("/api/data/v1/datasets?page=1&page_size=100", "dev-contributor")
    datasets = catalogue.get("items", [])
    gaul = find_title(datasets, "GAUL 2024 level-1 boundary")
    mpi = find_title(datasets, "MPI 2025 compatibility")
    for item, profile in (
        (gaul, "administrative-boundary@1.0"),
        (mpi, "normalised-indicator-layer@1.0"),
    ):
        current = item.get("current_published_version") or {}
        require(item.get("evidence_type") == "REAL_SAMPLE", f"{item['title']} lost REAL_SAMPLE evidence label")
        require(item.get("licence_status") == "NOT_CONFIRMED", f"{item['title']} licence warning is missing")
        require(current.get("state") == "PUBLISHED", f"{item['title']} is not published")
        require(current.get("profile_key") == profile, f"{item['title']} profile changed")

    gaul_version = gaul["current_published_version"]["id"]
    gaul_preview = get(
        f"/api/data/v1/versions/{gaul_version}/preview?page=1&page_size=5",
        "dev-contributor",
    )
    require(gaul_preview.get("preview_kind") == "vector", "GAUL preview is not vector")
    require(gaul_preview.get("page", {}).get("total") == 26, "GAUL preview count changed")
    mpi_version = mpi["current_published_version"]["id"]
    mpi_lineage = get(f"/api/data/v1/versions/{mpi_version}/lineage", "dev-contributor")
    require(bool(mpi_lineage), "MPI lineage is empty")
    report["checks"]["real_samples"] = {
        "gaul_features": 26,
        "mpi_quality": mpi.get("quality_status"),
        "licence": "not_confirmed",
    }

    input_sets = get(
        "/api/apps/investment-prioritisation/v1/input-sets?page_size=100",
        "dev-analyst",
    )["items"]
    real_set = next(item for item in input_sets if item.get("evidence_mode") == "REAL_SAMPLE")
    synthetic_set = next(
        item
        for item in input_sets
        if item.get("evidence_mode") == "SYNTHETIC_DEMO"
        and item.get("readiness", {}).get("ready")
    )
    require(not real_set.get("readiness", {}).get("ready"), "Incomplete real input set became runnable")
    require(synthetic_set.get("status") == "LOCKED", "Synthetic demonstration input is not locked")

    runs = get(
        "/api/apps/investment-prioritisation/v1/runs?page_size=100",
        "dev-analyst",
    )["items"]
    successful = [
        item
        for item in runs
        if item.get("status") in {"succeeded", "succeeded_with_warnings"}
        and item.get("result_count") == 111
    ]
    require(len(successful) >= 13, "Preserved successful run evidence is incomplete")
    require(
        any(item.get("result_checksum") == RESULT_SHA256 for item in successful),
        "Expected deterministic result checksum is absent",
    )
    report["checks"]["investment"] = {
        "real_readiness": False,
        "successful_runs": len(successful),
        "result_sha256": RESULT_SHA256,
    }

    cases = get(
        "/api/apps/extension-field-support/v1/cases",
        "dev-extension-supervisor",
    )
    worklist = get(
        "/api/apps/extension-field-support/v1/worklist",
        "dev-extension-officer-1",
    )
    require(cases.get("meta", {}).get("total") == 8, "Extension seed should contain eight cases")
    require(worklist.get("meta", {}).get("total") == 3, "Officer 1 assignment boundary changed")
    require(all(item.get("demonstration") for item in cases.get("items", [])), "A case lost its demonstration label")
    report["checks"]["extension"] = {"cases": 8, "officer_1_assigned": 3}

    system = get("/api/governance/v1/system-health", "dev-admin")
    for dependency in ("database", "object_storage", "redis", "worker", "migrations"):
        require(system.get("services", {}).get(dependency, {}).get("status") == "OK", f"Governance health {dependency} is not OK")
    require(system.get("services", {}).get("scanner", {}).get("status") == "WARNING", "Development scanner warning is not visible")
    require(system.get("latest_backup_evidence", {}).get("status") == "LOCAL_EVIDENCE_PRESENT", "Local backup evidence is absent")
    audit = get("/api/audit/v1/events?page=1&page_size=1", "dev-auditor")
    require(audit.get("meta", {}).get("total", 0) > 0, "Audit evidence is empty")
    report["checks"]["governance"] = {
        "migrations": system["services"]["migrations"]["current"],
        "scanner": "warning",
        "backup": "local_evidence_present",
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
