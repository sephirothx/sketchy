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


async def test_assets_remain_available_without_compression(static_app):
    app, _, asset = static_app

    status, headers, body = await request(app, "/assets/app-AbCdEf12.js")

    assert status == 200
    assert "content-encoding" not in headers
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert body == asset


@pytest.mark.parametrize("path", ["/", "/room/ABC123"])
async def test_spa_html_revalidates_for_root_and_client_routes(static_app, path):
    app, index, _ = static_app

    status, headers, body = await request(app, path)

    assert status == 200
    assert headers["cache-control"] == "no-cache"
    assert "immutable" not in headers["cache-control"]
    assert body == index


async def test_non_fingerprinted_files_revalidate(static_app):
    app, _, _ = static_app

    status, headers, body = await request(app, "/favicon.svg")

    assert status == 200
    assert headers["cache-control"] == "no-cache"
    assert body == b"<svg></svg>"


async def test_missing_file_with_extension_remains_a_404(static_app):
    app, _, _ = static_app

    status, _, _ = await request(app, "/missing.js")

    assert status == 404


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


@pytest.mark.parametrize("path", ["/nope", "/room/ABC123/extra", "/admin"])
async def test_an_unknown_client_route_gets_the_shell_with_a_404(static_app, path):
    """The page a browser can draw, and the status everything else reads.

    Serving the shell is what lets the client render its not-found page;
    answering 200 as well would tell a crawler or an uptime probe that a page
    exists where none does.
    """
    app, index, _ = static_app

    status, headers, body = await request(app, path)

    assert status == 404
    assert body == index
    assert headers["cache-control"] == "no-cache"


async def test_an_unknown_api_path_is_a_plain_404(static_app):
    """Never the SPA: an API client asking for a route that does not exist
    must get a 404 it can act on, not an HTML page it has to parse."""
    app, index, _ = static_app

    status, _, body = await request(app, "/api/nope")

    assert status == 404
    assert body != index


# --- Precompressed copies (#978) -------------------------------------------


def _write_build(tmp_path: Path) -> tuple[bytes, bytes]:
    index = b"<!doctype html><html><body>Sketchy frontend</body></html>" * 30
    asset = b"export const sketchy = 'precompressed asset';\n" * 100
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_bytes(index)
    (tmp_path / "index.html.gz").write_bytes(gzip.compress(index))
    (tmp_path / "index.html.br").write_bytes(b"BROTLI:" + index)
    (assets / "app-AbCdEf12.js").write_bytes(asset)
    (assets / "app-AbCdEf12.js.gz").write_bytes(gzip.compress(asset))
    # Not real Brotli: the server must hand the file over byte for byte, and a
    # marker proves it did not re-encode anything.
    (assets / "app-AbCdEf12.js.br").write_bytes(b"BROTLI:" + asset)
    (assets / "font-AbCdEf12.woff2").write_bytes(b"\x00woff2" * 400)
    return index, asset


@pytest.fixture
def built_app(tmp_path: Path, monkeypatch):
    """A build with the siblings the frontend's precompress step writes, and a
    compressor that fails the test if the server reaches for it."""
    index, asset = _write_build(tmp_path)

    class NoCompressing(gzip.GzipFile):
        # Starlette builds its compressor up front for every gzip-accepting
        # request, so constructing one proves nothing; writing to it does.
        def write(self, data):
            raise AssertionError("the server compressed a static file on the loop")

    import starlette.middleware.gzip as starlette_gzip

    monkeypatch.setattr(starlette_gzip.gzip, "GzipFile", NoCompressing)
    app = FastAPI()
    configure_frontend(app, tmp_path)
    return app, index, asset


async def test_an_asset_is_served_from_the_builds_brotli_copy(built_app):
    app, _, asset = built_app

    status, headers, body = await request(
        app, "/assets/app-AbCdEf12.js", headers={"Accept-Encoding": "gzip, deflate, br"}
    )

    assert status == 200
    assert body == b"BROTLI:" + asset
    assert headers["content-encoding"] == "br"
    assert headers["content-type"].startswith("text/javascript")
    assert "accept-encoding" in headers["vary"].lower()
    assert headers["cache-control"] == "public, max-age=31536000, immutable"
    assert int(headers["content-length"]) == len(body)


async def test_a_gzip_only_client_gets_the_gzip_copy(built_app):
    app, _, asset = built_app

    status, headers, body = await request(
        app, "/assets/app-AbCdEf12.js", headers={"Accept-Encoding": "gzip"}
    )

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == asset


@pytest.mark.parametrize("accept", ["br;q=0, gzip;q=0", "identity", ""])
async def test_a_coding_the_client_refuses_is_not_sent(built_app, accept):
    app, _, asset = built_app

    status, headers, body = await request(
        app, "/assets/app-AbCdEf12.js", headers={"Accept-Encoding": accept}
    )

    assert status == 200
    assert "content-encoding" not in headers
    assert body == asset


@pytest.mark.parametrize(("path", "expected"), [("/", 200), ("/room/ABC123", 200), ("/nope", 404)])
async def test_the_shell_is_served_precompressed_with_its_status(built_app, path, expected):
    app, index, _ = built_app

    status, headers, body = await request(app, path, headers={"Accept-Encoding": "br"})

    assert status == expected
    assert headers["content-encoding"] == "br"
    assert body == b"BROTLI:" + index
    assert headers["cache-control"] == "no-cache"


async def test_a_precompressed_copy_answers_conditional_requests(built_app):
    app, _, _ = built_app
    accept = {"Accept-Encoding": "br"}

    _, first, _ = await request(app, "/", headers=accept)
    status, headers, body = await request(
        app, "/", headers={**accept, "If-None-Match": first["etag"]}
    )

    assert status == 304
    assert body == b""
    assert headers["cache-control"] == "no-cache"


async def test_a_font_is_never_compressed(tmp_path: Path):
    """Compressed formats are passed through: a second pass only spends loop
    time making them slightly larger."""
    _write_build(tmp_path)
    app = FastAPI()
    configure_frontend(app, tmp_path)

    status, headers, body = await request(
        app, "/assets/font-AbCdEf12.woff2", headers={"Accept-Encoding": "gzip"}
    )

    assert status == 200
    assert "content-encoding" not in headers
    assert body == b"\x00woff2" * 400


def test_what_is_compressed_on_the_loop_is_compressed_cheaply():
    from app.compression import DYNAMIC_COMPRESSLEVEL, SelectiveGZipMiddleware

    assert SelectiveGZipMiddleware(app=None).compresslevel == DYNAMIC_COMPRESSLEVEL == 4


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("gzip, deflate, br", {"gzip", "deflate", "br"}),
        ("br;q=1.0, gzip;q=0.8", {"br", "gzip"}),
        ("gzip;q=0, br", {"br"}),
        ("GZIP; Q=0.5", {"gzip"}),
        ("br;q=nonsense", set()),
        (None, set()),
    ],
)
def test_accept_encoding_is_parsed_not_substring_matched(header, expected):
    from app.compression import accepted_encodings

    assert accepted_encodings(header) == expected


@pytest.mark.parametrize("path", ["/index.html.gz", "/index.html.br", "/assets/app-AbCdEf12.js.gz", "/assets/app-AbCdEf12.js.br"])
async def test_a_precompressed_copy_is_not_served_under_its_own_name(built_app, path):
    """Asked for directly, a copy would go out as the original's type with no
    Content-Encoding and a compressed body."""
    app, _, _ = built_app

    status, _, _ = await request(app, path, headers={"Accept-Encoding": "br, gzip"})

    assert status == 404


@pytest.mark.parametrize("validator", ["If-None-Match", "If-Modified-Since"])
async def test_the_not_found_shell_ignores_validators_meant_for_another_url(built_app, validator):
    """A validator that happens to match the shell must not turn the page that
    draws "not found" into a 404 with no body."""
    app, index, _ = built_app
    _, root, _ = await request(app, "/")
    value = root["etag"] if validator == "If-None-Match" else "Fri, 01 Jan 2100 00:00:00 GMT"

    status, _, body = await request(app, "/nope", headers={validator: value})

    assert status == 404
    assert body == index
