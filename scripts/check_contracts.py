from __future__ import annotations

import ast
import csv
import json
import os
import re
import subprocess
from pathlib import Path

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "api" / "app" / "module_manifests"
SCHEMA_PATH = MANIFEST_DIR / "module-contract.schema.json"
MIGRATION_DIR = ROOT / "api" / "alembic" / "versions"


class ContractCheckError(RuntimeError):
    pass


def _tracked_files() -> list[str]:
    inventory_path = os.getenv("CONTRACT_TRACKED_FILES_FILE")
    if inventory_path:
        return [
            item
            for item in Path(inventory_path).read_text(encoding="utf-8").splitlines()
            if item
        ]
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [item.decode() for item in completed.stdout.split(b"\0") if item]


def check_repository_hygiene(tracked: list[str]) -> None:
    forbidden_names = (
        re.compile(r"(^|/)[A-Z0-9_-]*PROMPT_.*\.md$", re.IGNORECASE),
        re.compile(r"(^|/)(?:CHAT|CONVERSATION|ASSISTANT)_[A-Z0-9_-]*\.md$", re.IGNORECASE),
        re.compile(r"(^|/)PROJECT_HANDOFF_CONTEXT_.*\.md$", re.IGNORECASE),
        re.compile(r"(^|/)backups/", re.IGNORECASE),
        re.compile(r"(^|/)\.env$"),
        re.compile(r"\.(dump|sql\.gz)$", re.IGNORECASE),
    )
    forbidden = sorted(
        name for name in tracked if any(pattern.search(name) for pattern in forbidden_names)
    )
    if forbidden:
        raise ContractCheckError(f"Forbidden tracked files: {', '.join(forbidden)}")


def check_secret_patterns(tracked: list[str]) -> None:
    patterns = {
        "GitHub access token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
        "AWS access key": re.compile(rb"AKIA[0-9A-Z]{16}"),
        "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    }
    findings: list[str] = []
    for relative in tracked:
        file_path = ROOT / relative
        if not file_path.is_file() or file_path.stat().st_size > 2_000_000:
            continue
        content = file_path.read_bytes()
        for label, pattern in patterns.items():
            if pattern.search(content):
                findings.append(f"{relative}: {label}")
    if findings:
        raise ContractCheckError("Secret-pattern findings: " + "; ".join(findings))


def check_manifests() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    manifests: list[dict] = []
    for manifest_path in sorted(MANIFEST_DIR.glob("*.module.yaml")):
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(manifest), key=lambda item: list(item.path))
        if errors:
            details = "; ".join(
                f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}"
                for error in errors
            )
            raise ContractCheckError(f"{manifest_path.name}: {details}")
        manifests.append(manifest)

    module_keys = [manifest["module"]["key"] for manifest in manifests]
    if len(module_keys) != len(set(module_keys)):
        raise ContractCheckError("Duplicate module keys")

    for manifest in manifests:
        declared = [item["code"] for item in manifest["permissions"]["declared"]]
        if len(declared) != len(set(declared)):
            raise ContractCheckError(
                f"Duplicate permissions in {manifest['module']['key']} manifest"
            )
        declared_set = set(declared)
        used = set(manifest["permissions"]["required_to_enter"])
        for route in manifest["routes"]:
            used.update(route["permissions"])
        missing = sorted(used - declared_set)
        if missing:
            raise ContractCheckError(
                f"Undeclared route permissions for {manifest['module']['key']}: "
                + ", ".join(missing)
            )

    matrix_path = ROOT / "docs" / "architecture" / "blueprint-v0.1" / "permission-matrix.csv"
    with matrix_path.open(encoding="utf-8-sig", newline="") as handle:
        matrix_codes = [row["permission_code"] for row in csv.DictReader(handle)]
    if len(matrix_codes) != len(set(matrix_codes)):
        raise ContractCheckError("Duplicate permission codes in the permission matrix")


def _migration_value(file_path: Path, field: str):
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == field for target in targets):
                return ast.literal_eval(node.value)
    raise ContractCheckError(f"{file_path.name} does not declare {field}")


def check_migrations() -> None:
    migrations: dict[str, str | None] = {}
    for file_path in sorted(MIGRATION_DIR.glob("*.py")):
        if file_path.name.startswith("__"):
            continue
        revision = _migration_value(file_path, "revision")
        down_revision = _migration_value(file_path, "down_revision")
        if not isinstance(revision, str) or not revision:
            raise ContractCheckError(f"Invalid revision in {file_path.name}")
        if revision in migrations:
            raise ContractCheckError(f"Duplicate Alembic revision: {revision}")
        if down_revision is not None and not isinstance(down_revision, str):
            raise ContractCheckError(f"Merge/fork revisions require an explicit review: {file_path.name}")
        migrations[revision] = down_revision

    unknown_parents = sorted(
        parent for parent in migrations.values() if parent is not None and parent not in migrations
    )
    if unknown_parents:
        raise ContractCheckError("Unknown Alembic parents: " + ", ".join(unknown_parents))
    parents = {parent for parent in migrations.values() if parent is not None}
    heads = sorted(set(migrations) - parents)
    if len(heads) != 1:
        raise ContractCheckError(f"Expected one Alembic head, found: {heads}")


def main() -> None:
    tracked = _tracked_files()
    check_repository_hygiene(tracked)
    check_secret_patterns(tracked)
    check_manifests()
    check_migrations()
    print("Repository, module contracts, secret patterns and migration graph passed.")


if __name__ == "__main__":
    main()
