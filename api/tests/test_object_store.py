from app import object_store


class CapturingClient:
    def __init__(self) -> None:
        self.arguments = None

    def presigned_get_object(self, *args, **kwargs) -> str:
        self.arguments = (args, kwargs)
        return "https://storage.example.test/signed"


def test_presigned_download_forces_attachment_with_original_filename(monkeypatch) -> None:
    client = CapturingClient()
    monkeypatch.setattr(object_store, "public_object_client", lambda: client)

    url = object_store.presigned_get(
        "catalog/example/source/1",
        filename="Cambodia boundary — demo.geojson",
        media_type="application/geo+json",
    )

    assert url == "https://storage.example.test/signed"
    assert client.arguments is not None
    _, kwargs = client.arguments
    headers = kwargs["response_headers"]
    assert headers["response-content-disposition"].startswith(
        'attachment; filename="Cambodia boundary  demo.geojson"; filename*=UTF-8\'\''
    )
    assert "%E2%80%94" in headers["response-content-disposition"]
    assert headers["response-content-type"] == "application/geo+json"
    assert headers["response-cache-control"] == "private, no-store"


def test_presigned_inline_asset_keeps_default_response_headers(monkeypatch) -> None:
    client = CapturingClient()
    monkeypatch.setattr(object_store, "public_object_client", lambda: client)

    object_store.presigned_get("catalog/example/preview/1")

    assert client.arguments is not None
    _, kwargs = client.arguments
    assert kwargs["response_headers"] is None


def test_internal_http_and_browser_https_clients_use_separate_transports(monkeypatch) -> None:
    calls = []

    def capture_client(endpoint, **kwargs):
        calls.append((endpoint, kwargs))
        return object()

    monkeypatch.setattr(object_store, "Minio", capture_client)
    monkeypatch.setattr(object_store, "OBJECT_STORE_INTERNAL_ENDPOINT", "minio:9000")
    monkeypatch.setattr(object_store, "OBJECT_STORE_INTERNAL_SECURE", False)
    monkeypatch.setattr(object_store, "OBJECT_STORE_PUBLIC_ENDPOINT", "storage.example.test")
    monkeypatch.setattr(object_store, "OBJECT_STORE_SECURE", True)

    object_store.object_client()
    object_store.public_object_client()

    assert calls[0][0] == "minio:9000"
    assert calls[0][1]["secure"] is False
    assert calls[1][0] == "storage.example.test"
    assert calls[1][1]["secure"] is True
