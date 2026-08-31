from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


MANIFEST_DIR = Path(__file__).with_name("module_manifests")


def load_validated_manifests(directory: Path = MANIFEST_DIR) -> list[dict[str, Any]]:
    schema = json.loads((directory / "module-contract.schema.json").read_text())
    validator = Draft202012Validator(schema)
    manifests: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.module.yaml")):
        manifest = yaml.safe_load(path.read_text())
        errors = sorted(validator.iter_errors(manifest), key=lambda item: list(item.path))
        if errors:
            messages = "; ".join(error.message for error in errors[:5])
            raise RuntimeError(f"Invalid module manifest {path.name}: {messages}")
        manifests.append(manifest)
    if not manifests:
        raise RuntimeError("No module manifests were found.")
    return manifests
