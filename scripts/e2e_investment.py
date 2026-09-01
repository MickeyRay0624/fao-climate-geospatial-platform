from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid


BASE_URL = "http://localhost:8000/api/apps/investment-prioritisation/v1"
HEADERS = {"X-Dev-User-Subject": "dev-analyst"}
EXPECTED_RESULT_CHECKSUM = "741279cd97aed25f568c4dd8fc02cda6877acf3f65efe922af5d361db1841f54"


def request_json(method: str, endpoint: str, body: dict | None = None, key: str | None = None):
    headers = dict(HEADERS)
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if key:
        headers["Idempotency-Key"] = key
    request = urllib.request.Request(
        f"{BASE_URL}{endpoint}", data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        details = error.read().decode(errors="replace")
        raise RuntimeError(f"{method} {endpoint} failed with {error.code}: {details}") from error


def main() -> None:
    input_sets = request_json("GET", "/input-sets?page_size=100")["items"]
    input_set = next(
        item
        for item in input_sets
        if item["status"] == "LOCKED"
        and item["profile_mode"] == "SEPARATE_LAYERS"
        and item["readiness"]["ready"]
    )
    methods = request_json("GET", "/methods?page_size=100")["items"]
    method_version = next(
        version
        for method in methods
        for version in method["versions"]
        if version["state"] == "APPROVED"
    )
    scenarios = request_json("GET", "/scenarios?page_size=100")["items"]
    scenario = next(
        item
        for item in scenarios
        if item["state"] == "APPROVED" and item["method_version_id"] == method_version["id"]
    )
    run = request_json(
        "POST",
        "/runs",
        {
            "input_set_id": input_set["id"],
            "method_version_id": method_version["id"],
            "scenario_id": scenario["id"],
            "run_mode": "FORMAL",
            "overrides": {},
        },
        key=f"ci-investment-{uuid.uuid4()}",
    )
    run_id = run["id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        run = request_json("GET", f"/runs/{run_id}")
        if run["status"] in {"succeeded", "succeeded_with_warnings"}:
            break
        if run["status"] in {"failed", "cancelled"}:
            raise RuntimeError(f"Investment run ended in {run['status']}: {run.get('failure')}")
        time.sleep(1)
    else:
        raise RuntimeError("Investment run did not complete within 120 seconds")

    results = request_json("GET", f"/runs/{run_id}/results?page_size=500")
    assert results["meta"]["total"] == 111, results["meta"]
    assert results["result_checksum"] == EXPECTED_RESULT_CHECKSUM
    top = min(results["items"], key=lambda item: item["rank"] or 10_000)
    assert top["name"] == "Prey Veng Demo Commune 03", top
    assert float(top["score"]) == 65.32, top
    print(
        json.dumps(
            {
                "status": "passed",
                "run_id": run_id,
                "result_count": results["meta"]["total"],
                "result_checksum": results["result_checksum"],
                "rank_1": top["name"],
                "score": top["score"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
