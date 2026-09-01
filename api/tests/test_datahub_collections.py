from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.datahub.router import _table_page, _vector_page
from app.main import app
from app.platform_models import CatalogDatasetVersion, Collection


client = TestClient(app)
ADMIN = {"X-Dev-User-Subject": "dev-admin"}


def test_exact_version_collection_lifecycle_is_idempotent_and_non_destructive() -> None:
    suffix = uuid4().hex[:12]
    key = f"collection-create-{suffix}"
    headers = {**ADMIN, "Idempotency-Key": key}
    body = {
        "title": f"Temporary exact-version collection {suffix}",
        "description": "Synthetic collection lifecycle verification.",
        "tags": ["synthetic", "verification"],
    }
    first = client.post("/api/data/v1/collections", headers=headers, json=body)
    replay = client.post("/api/data/v1/collections", headers=headers, json=body)
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    collection_id = first.json()["id"]

    with SessionLocal() as session:
        version_id = session.scalar(
            select(CatalogDatasetVersion.id)
            .where(CatalogDatasetVersion.state == "PUBLISHED")
            .order_by(CatalogDatasetVersion.created_at)
        )
    added = client.post(
        f"/api/data/v1/collections/{collection_id}/members",
        headers={**ADMIN, "Idempotency-Key": f"collection-member-{suffix}"},
        json={"dataset_version_id": str(version_id), "role": "evidence", "ordinal": 1},
    )
    assert added.status_code == 201
    assert added.json()["member_count"] == 1
    assert added.json()["members"][0]["version"]["id"] == str(version_id)

    archived = client.post(
        f"/api/data/v1/collections/{collection_id}/archive",
        headers={**ADMIN, "Idempotency-Key": f"collection-archive-{suffix}"},
        json={
            "row_version": added.json()["row_version"],
            "reason": "Lifecycle verification retains evidence without physical deletion.",
        },
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"
    denied = client.post(
        f"/api/data/v1/collections/{collection_id}/members",
        headers={**ADMIN, "Idempotency-Key": f"collection-after-archive-{suffix}"},
        json={"dataset_version_id": str(version_id), "role": "duplicate", "ordinal": 2},
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "COLLECTION_ARCHIVED"

    with SessionLocal() as session:
        item = session.get(Collection, UUID(collection_id))
        assert item is not None
        session.delete(item)
        session.commit()


def test_vector_preview_is_paginated_simplified_and_display_capped() -> None:
    features = [
        {
            "type": "Feature",
            "properties": {"area_code": f"A-{index}"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[104, 11], [104.01, 11], [104.01, 11.01], [104, 11]]],
            },
        }
        for index in range(2005)
    ]
    import json

    preview, total = _vector_page(
        json.dumps({"type": "FeatureCollection", "features": features}).encode(),
        page=80,
        page_size=25,
        simplify_tolerance=0.002,
    )

    assert total == 2005
    assert len(preview["features"]) == 25
    assert preview["features"][0]["properties"]["area_code"] == "A-1975"


def test_sensitive_table_preview_redacts_direct_identifiers() -> None:
    rows, total, statistics = _table_page(
        b"area_code,farmer_name,phone,value\nA-1,Demo Person,000,0.4\n",
        page=1,
        page_size=25,
        redact_sensitive=True,
    )

    assert total == 1
    assert rows[0]["area_code"] == "A-1"
    assert rows[0]["farmer_name"] == "[REDACTED]"
    assert rows[0]["phone"] == "[REDACTED]"
    assert statistics["redacted_fields"] == ["farmer_name", "phone"]
