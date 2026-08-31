from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.platform_models import AuditEvent


SENSITIVE_KEYS = {"password", "secret", "token", "access_key", "object_key", "authorization"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def record_event(
    session: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | UUID,
    outcome: str,
    correlation_id: str,
    actor_id: UUID | None = None,
    workspace_id: UUID | None = None,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    severity: str = "INFO",
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor_id,
        workspace_id=workspace_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        outcome=outcome,
        reason=reason,
        correlation_id=correlation_id,
        before_json=_redact(before or {}),
        after_json=_redact(after or {}),
        severity=severity,
    )
    session.add(event)
    return event
