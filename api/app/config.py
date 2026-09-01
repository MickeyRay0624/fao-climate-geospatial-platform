from __future__ import annotations

import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://rice_dss:rice_demo_change_me@localhost:5432/rice_dss",
)

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

DEMO_DISCLAIMER = (
    "Synthetic demonstration data — not for operational planning, funding decisions, "
    "or agronomic advice. Replace all boundaries and indicators with validated sources."
)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "dss_local_admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "dss_local_storage_change_me")
OBJECT_STORE_BUCKET = os.getenv("OBJECT_STORE_BUCKET", os.getenv("MINIO_BUCKET", "dss-data"))
# Retain the legacy import name while making the platform setting authoritative.
MINIO_BUCKET = OBJECT_STORE_BUCKET
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))

# Platform runtime and identity boundary. Development identity headers are a
# deliberate local-only capability; a shared/staging runtime fails closed.
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
AUTH_MODE = os.getenv("AUTH_MODE", "dev").strip().lower()
ALLOW_DEV_IDENTITY_HEADERS = _bool("ALLOW_DEV_IDENTITY_HEADERS", True)
DEFAULT_DEV_USER_SUBJECT = os.getenv("DEFAULT_DEV_USER_SUBJECT", "dev-admin")
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "")
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", "")

OBJECT_STORE_INTERNAL_ENDPOINT = os.getenv("OBJECT_STORE_INTERNAL_ENDPOINT", MINIO_ENDPOINT)
OBJECT_STORE_PUBLIC_ENDPOINT = os.getenv(
    "OBJECT_STORE_PUBLIC_ENDPOINT", "localhost:9000"
)
OBJECT_STORE_SECURE = _bool("OBJECT_STORE_SECURE", MINIO_SECURE)
OBJECT_STORE_REGION = os.getenv("OBJECT_STORE_REGION", "us-east-1")
PRESIGNED_URL_TTL_SECONDS = int(os.getenv("PRESIGNED_URL_TTL_SECONDS", "900"))
MAX_DATA_HUB_UPLOAD_BYTES = int(
    os.getenv("MAX_DATA_HUB_UPLOAD_BYTES", str(100 * 1024 * 1024))
)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = _bool("CELERY_TASK_ALWAYS_EAGER", False)
ALLOW_INSECURE_DEV_FILE_SCAN = _bool("ALLOW_INSECURE_DEV_FILE_SCAN", True)


def validate_security_configuration() -> None:
    if APP_ENV not in {"development", "test"} and (
        AUTH_MODE == "dev" or ALLOW_DEV_IDENTITY_HEADERS
    ):
        raise RuntimeError(
            "Development identity mode is forbidden outside development/test."
        )
    if AUTH_MODE not in {"dev", "oidc"}:
        raise RuntimeError("AUTH_MODE must be either 'dev' or 'oidc'.")
    if AUTH_MODE == "oidc" and not (OIDC_ISSUER and OIDC_AUDIENCE and OIDC_JWKS_URL):
        raise RuntimeError("OIDC mode requires issuer, audience, and JWKS URL.")
    if APP_ENV not in {"development", "test"} and ALLOW_INSECURE_DEV_FILE_SCAN:
        raise RuntimeError("Development file-scan bypass is forbidden outside development/test.")


validate_security_configuration()
