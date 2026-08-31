from __future__ import annotations

import io
import time

from minio import Minio
from minio.error import S3Error

from app.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)


def object_client() -> Minio:
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def ensure_bucket(retries: int = 1, delay_seconds: float = 1.0) -> None:
    client = object_client()
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            if not client.bucket_exists(MINIO_BUCKET):
                client.make_bucket(MINIO_BUCKET)
            return
        except Exception as error:  # network readiness is the expected retry case
            last_error = error
            if attempt < retries - 1:
                time.sleep(delay_seconds)
    if last_error:
        raise last_error


def put_bytes(object_key: str, payload: bytes, content_type: str) -> None:
    ensure_bucket()
    object_client().put_object(
        MINIO_BUCKET,
        object_key,
        io.BytesIO(payload),
        length=len(payload),
        content_type=content_type,
    )


def get_bytes(object_key: str) -> bytes:
    response = object_client().get_object(MINIO_BUCKET, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def remove_object(object_key: str) -> None:
    try:
        object_client().remove_object(MINIO_BUCKET, object_key)
    except S3Error:
        pass

