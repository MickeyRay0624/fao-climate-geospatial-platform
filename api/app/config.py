from __future__ import annotations

import os


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
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "dss-data")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))

