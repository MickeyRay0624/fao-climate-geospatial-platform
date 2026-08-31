import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.audit_service import record_event
from app.datahub.schemas import CreateDatasetRequest, CreateGrantRequest, UploadFileSpec
from app.module_registry import MANIFEST_DIR, load_validated_manifests


class CapturingSession:
    def __init__(self) -> None:
        self.added = []

    def add(self, value) -> None:
        self.added.append(value)


def test_module_manifests_validate_against_contract() -> None:
    manifests = load_validated_manifests()

    assert {item["module"]["key"] for item in manifests} == {
        "extension-field-support",
        "investment-prioritisation",
    }


def test_invalid_module_manifest_fails_seed_boundary(tmp_path: Path) -> None:
    (tmp_path / "module-contract.schema.json").write_text(
        (MANIFEST_DIR / "module-contract.schema.json").read_text()
    )
    (tmp_path / "invalid.module.yaml").write_text("key: missing-required-contract-fields\n")

    with pytest.raises(RuntimeError, match="Invalid module manifest"):
        load_validated_manifests(tmp_path)


def test_sensitive_field_classification_cannot_be_public() -> None:
    with pytest.raises(ValidationError, match="SENSITIVE_FIELD data cannot be PUBLIC"):
        CreateDatasetRequest(
            title="Sensitive observations",
            abstract="Potentially identifiable field observations.",
            data_kind="vector",
            visibility="PUBLIC",
            classification="SENSITIVE_FIELD",
        )


def test_resource_grant_expiry_must_be_future_and_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="expires_at must include a timezone"):
        CreateGrantRequest(
            subject_type="user",
            subject_id="00000000-0000-0000-0000-000000000001",
            permission_code="dataset.download",
            effect="ALLOW",
            expires_at="2026-09-01T00:00:00",
            reason="Temporary test access",
        )

    with pytest.raises(ValidationError, match="expires_at must be in the future"):
        CreateGrantRequest(
            subject_type="user",
            subject_id="00000000-0000-0000-0000-000000000001",
            permission_code="dataset.download",
            effect="ALLOW",
            expires_at="2020-01-01T00:00:00Z",
            reason="Expired test access",
        )


@pytest.mark.parametrize("filename", ["../escape.csv", "folder/file.csv", "folder\\file.csv", ".."])
def test_upload_filename_cannot_escape_quarantine_prefix(filename: str) -> None:
    with pytest.raises(ValidationError, match="filename must not contain a path"):
        UploadFileSpec(filename=filename, media_type="text/csv", size_bytes=10)


def test_audit_payload_redacts_nested_secrets() -> None:
    session = CapturingSession()
    event = record_event(
        session,
        action="security.test",
        resource_type="dataset",
        resource_id="resource-1",
        outcome="success",
        correlation_id="correlation-1",
        before={"token": "secret-token", "nested": [{"object_key": "private/path"}]},
        after={"safe": "retained", "authorization": "Bearer secret"},
    )

    assert session.added == [event]
    assert event.before_json == {"token": "[REDACTED]", "nested": [{"object_key": "[REDACTED]"}]}
    assert event.after_json == {"safe": "retained", "authorization": "[REDACTED]"}


def test_production_rejects_development_identity_mode() -> None:
    environment = {
        **os.environ,
        "APP_ENV": "production",
        "AUTH_MODE": "dev",
        "ALLOW_DEV_IDENTITY_HEADERS": "true",
        "ALLOW_INSECURE_DEV_FILE_SCAN": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Development identity mode is forbidden" in result.stderr


def test_oidc_mode_requires_complete_validation_configuration() -> None:
    environment = {
        **os.environ,
        "APP_ENV": "production",
        "AUTH_MODE": "oidc",
        "ALLOW_DEV_IDENTITY_HEADERS": "false",
        "ALLOW_INSECURE_DEV_FILE_SCAN": "false",
        "OIDC_ISSUER": "",
        "OIDC_AUDIENCE": "",
        "OIDC_JWKS_URL": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "OIDC mode requires issuer, audience, and JWKS URL" in result.stderr
