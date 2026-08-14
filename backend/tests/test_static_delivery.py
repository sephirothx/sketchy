import gzip
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.main import configure_frontend


async def request(
    app,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
):
    sent = []
    request_delivered = False

    async def receive():
        nonlocal request_delivered
        if request_delivered:
            return {"type": "http.disconnect"}
        request_delivered = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    encoded_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": encoded_headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    await app(scope, receive, send)

    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    response_headers = {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in start["headers"]
    }
    return start["status"], response_headers, body


@pytest.fixture
def static_app(tmp_path: Path):
    index = b"<!doctype html><html><body>Sketchy frontend</body></html>"
    asset = (b"export const sketchy = 'compressed asset';\n" * 100)

    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_bytes(index)
    (tmp_path / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    (assets / "app-AbCdEf12.js").write_bytes(asset)

    app = FastAPI()
    configure_frontend(app, tmp_path)
    return app, index, asset


@pytest.mark.asyncio
async def test_fingerprinted_assets_are_compressed_and_cached_immutably(static_app):
    app, _, asset = static_app

    status, headers, body = await request(
        app,
        "/assets/app-AbCdEf12.js",
        headers={"Accept-Encoding": "gzip"},
    )

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert "accept-encoding" in headers["vary"].lower()
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert gzip.decompress(body) == asset


@pytest.mark.asyncio
async def test_assets_remain_available_without_compression(static_app):
    app, _, asset = static_app

    status, headers, body = await request(app, "/assets/app-AbCdEf12.js")

    assert status == 200
    assert "content-encoding" not in headers
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert body == asset


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/room/ABC123"])
async def test_spa_html_revalidates_for_root_and_client_routes(static_app, path):
    app, index, _ = static_app

    status, headers, body = await request(app, path)

    assert status == 200
    assert headers["cache-control"] == "no-cache"
    assert "immutable" not in headers["cache-control"]
    assert body == index


@pytest.mark.asyncio
async def test_non_fingerprinted_files_revalidate(static_app):
    app, _, _ = static_app

    status, headers, body = await request(app, "/favicon.svg")

    assert status == 200
    assert headers["cache-control"] == "no-cache"
    assert body == b"<svg></svg>"


@pytest.mark.asyncio
async def test_missing_file_with_extension_remains_a_404(static_app):
    app, _, _ = static_app

    status, _, _ = await request(app, "/missing.js")

    assert status == 404


@pytest.mark.asyncio
async def test_head_and_conditional_asset_requests_preserve_cache_headers(static_app):
    app, _, asset = static_app

    status, headers, body = await request(
        app,
        "/assets/app-AbCdEf12.js",
        method="HEAD",
    )
    assert status == 200
    assert body == b""
    assert int(headers["content-length"]) == len(asset)
    assert headers["cache-control"] == "public, max-age=31536000, immutable"

    status, first_headers, _ = await request(app, "/assets/app-AbCdEf12.js")
    assert status == 200
    status, conditional_headers, conditional_body = await request(
        app,
        "/assets/app-AbCdEf12.js",
        headers={"If-None-Match": first_headers["etag"]},
    )
    assert status == 304
    assert conditional_body == b""
    assert conditional_headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )
