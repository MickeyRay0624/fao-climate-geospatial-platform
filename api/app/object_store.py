from __future__ import annotations

import io
import re
import time
from datetime import timedelta
from urllib.parse import quote

from minio import Minio
from minio.error import S3Error

from app.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    OBJECT_STORE_INTERNAL_ENDPOINT,
    OBJECT_STORE_INTERNAL_SECURE,
    OBJECT_STORE_PUBLIC_ENDPOINT,
    OBJECT_STORE_REGION,
    OBJECT_STORE_SECURE,
    PRESIGNED_URL_TTL_SECONDS,
)


def object_client() -> Minio:
    return Minio(
        OBJECT_STORE_INTERNAL_ENDPOINT or MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=OBJECT_STORE_INTERNAL_SECURE,
    )


def public_object_client() -> Minio:
    """Client used only to sign browser-facing URLs; credentials never leave the API."""

    return Minio(
        OBJECT_STORE_PUBLIC_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=OBJECT_STORE_SECURE,
        region=OBJECT_STORE_REGION,
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


def presigned_put(object_key: str, ttl_seconds: int = PRESIGNED_URL_TTL_SECONDS) -> str:
    return public_object_client().presigned_put_object(
        MINIO_BUCKET, object_key, expires=timedelta(seconds=ttl_seconds)
    )


def _attachment_content_disposition(filename: str) -> str:
    cleaned = (
        filename.replace("\r", "")
        .replace("\n", "")
        .replace("/", "_")
        .replace("\\", "_")
    )
    ascii_fallback = cleaned.encode("ascii", "ignore").decode("ascii")
    ascii_fallback = (
        re.sub(r"[^A-Za-z0-9._ -]+", "_", ascii_fallback).strip(" .")
        or "download"
    )
    encoded = quote(cleaned, safe="")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


def presigned_get(
    object_key: str,
    ttl_seconds: int = PRESIGNED_URL_TTL_SECONDS,
    *,
    filename: str | None = None,
    media_type: str | None = None,
) -> str:
    response_headers = None
    if filename:
        response_headers = {
            "response-content-disposition": _attachment_content_disposition(filename),
            "response-content-type": media_type or "application/octet-stream",
            "response-cache-control": "private, no-store",
        }
    return public_object_client().presigned_get_object(
        MINIO_BUCKET,
        object_key,
        expires=timedelta(seconds=ttl_seconds),
        response_headers=response_headers,
    )


def stat_object(object_key: str):
    return object_client().stat_object(MINIO_BUCKET, object_key)


def copy_object(source_key: str, destination_key: str) -> None:
    from minio.commonconfig import CopySource

    object_client().copy_object(
        MINIO_BUCKET,
        destination_key,
        CopySource(MINIO_BUCKET, source_key),
    )
