from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def source_tree_sha256() -> str:
    """Hash the Python source actually mounted in the API/worker container."""

    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def execution_metadata() -> dict[str, Any]:
    digest = os.getenv("CONTAINER_IMAGE_DIGEST", "").strip()
    code_ref = os.getenv("CODE_VERSION_REF", "working-tree/uncommitted").strip()
    return {
        "code_ref": code_ref,
        "source_tree_sha256": source_tree_sha256(),
        "image_tag": os.getenv("CONTAINER_IMAGE_TAG", "cambodia-rice-dss-api:local"),
        "image_digest": digest or None,
        "image_digest_verified": bool(digest),
        "build_id": os.getenv("BUILD_ID", "local-compose"),
    }
