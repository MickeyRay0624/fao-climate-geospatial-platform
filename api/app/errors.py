from __future__ import annotations

from typing import Any


class PlatformError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def conflict(code: str, message: str, **details: Any) -> PlatformError:
    return PlatformError(code, message, 409, details)


def forbidden(code: str = "FORBIDDEN", message: str = "You are not authorised to perform this action.") -> PlatformError:
    return PlatformError(code, message, 403)


def not_found(resource: str = "Resource") -> PlatformError:
    # The same response is used for hidden and missing resources to avoid existence disclosure.
    return PlatformError("RESOURCE_NOT_FOUND", f"{resource} was not found.", 404)
