"""Static files go out as the build compressed them, not compressed per request (#978)."""
from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import DYNAMIC_GZIP_LEVEL, configure_frontend

BUNDLE = b"console.log('sketchy');\n" * 400  # ~10 KB, well past the middleware's floor


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc123.js").write_bytes(BUNDLE)
    # Marked, so a test can tell the build's copy from one compressed on the fly.
    (assets / "index-abc123.js.gz").write_bytes(gzip.compress(b"/*built*/" + BUNDLE, 9))
    (assets / "index-abc123.js.br").write_bytes(b"brotli-bytes-stand-in")
    (assets / "plain-def456.js").write_bytes(BUNDLE)  # built without copies
    (assets / "font-789.woff2").write_bytes(bytes(range(256)) * 20)
    (tmp_path / "index.html").write_bytes(b"<!doctype html><title>Sketchy</title>" + b" " * 2000)
    return tmp_path


@pytest.fixture
async def client(dist):
    app = FastAPI()

    @app.get("/api/big")
    async def big():
        return {"rows": ["x" * 40] * 200}

    configure_frontend(app, dist)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_the_brotli_copy_is_served_when_the_browser_takes_it(client, dist):
    response = await client.get("/assets/index-abc123.js", headers={"Accept-Encoding": "br, gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "br"
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["vary"] == "Accept-Encoding"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert int(response.headers["content-length"]) == len(b"brotli-bytes-stand-in")


async def test_the_gzip_copy_is_served_as_built_not_recompressed(client):
    response = await client.get("/assets/index-abc123.js", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.content == b"/*built*/" + BUNDLE


async def test_a_copy_answers_a_revalidation_with_its_own_validator(client):
    first = await client.get("/assets/index-abc123.js", headers={"Accept-Encoding": "gzip"})
    again = await client.get(
        "/assets/index-abc123.js",
        headers={"Accept-Encoding": "gzip", "If-None-Match": first.headers["etag"]},
    )
    assert again.status_code == 304


async def test_without_a_copy_the_original_is_served_and_compressed_on_the_fly(client):
    response = await client.get("/assets/plain-def456.js", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip" and response.content == BUNDLE
    identity = await client.get("/assets/index-abc123.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in identity.headers and identity.content == BUNDLE


async def test_an_already_compressed_format_is_never_gzipped(client):
    response = await client.get("/assets/font-789.woff2", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200 and "content-encoding" not in response.headers


async def test_dynamic_responses_are_gzipped_at_the_cheaper_level(client):
    response = await client.get("/api/big", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.json()["rows"][0] == "x" * 40
    assert DYNAMIC_GZIP_LEVEL == 4
