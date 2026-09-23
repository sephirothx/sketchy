"""Static delivery: cache policy, the build's compressed copies, and their validators.

R-PLAT-09, #978.
"""
import gzip
import os
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


def _compressed(payload: bytes, coding: str) -> bytes:
    """What the build writes beside a file. Brotli is not re-encoded by the
    server, so a marker stands in for it, as elsewhere in this file."""
    return gzip.compress(payload) if coding == "gzip" else b"BROTLI:" + payload


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


async def test_a_file_the_build_left_uncompressed_is_not_compressed_per_request(static_app):
    """The loop compresses nothing static (#978): what the build made a copy of
    is served from the copy, and what it left alone - text too small for a copy
    to be worth writing - goes out stored. Compressing here would also give two
    bodies one `ETag`, since the validator is the stored file's (#1045)."""
    app, _, asset = static_app

    status, headers, body = await request(
        app,
        "/assets/app-AbCdEf12.js",
        headers={"Accept-Encoding": "gzip, br"},
    )
    _, identity, _ = await request(
        app, "/assets/app-AbCdEf12.js", headers={"Accept-Encoding": "identity"}
    )

    assert status == 200
    assert "content-encoding" not in headers
    assert body == asset
    assert headers["etag"] == identity["etag"], "one ETag, one body"
    # Exactly once: two layers used to add it, and a doubled `Vary` is a
    # header a cache has to parse twice to learn nothing (#978 sixth review).
    assert headers["vary"] == "Accept-Encoding"
    assert headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_an_api_answer_is_still_compressed_on_the_loop(tmp_path: Path):
    """Only the static files opt out. What has no stored copy to serve - an
    API answer composed for this caller - is still compressed."""
    app = FastAPI()

    @app.get("/api/lots-of-json")
    async def lots_of_json():
        return {"values": ["compress me" for _ in range(200)]}

    (tmp_path / "index.html").write_bytes(b"<!doctype html><html></html>")
    configure_frontend(app, tmp_path)

    status, headers, body = await request(
        app, "/api/lots-of-json", headers={"Accept-Encoding": "gzip"}
    )

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    assert b"compress me" in gzip.decompress(body)


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
    # Once, not twice: the copy and the caller both used to add it (#978
    # sixth review).
    assert headers["vary"] == "Accept-Encoding"
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


@pytest.mark.parametrize(
    "path",
    [
        "/index.html.gz",
        "/index.html.br",
        "/assets/app-AbCdEf12.js.gz",
        "/assets/app-AbCdEf12.js.br",
        # A case-insensitive filesystem - APFS, NTFS - answers these with the
        # copy, so the guard matches without case too (#978 third review).
        "/assets/app-AbCdEf12.js.BR",
        "/assets/app-AbCdEf12.js.Gz",
    ],
)
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


@pytest.mark.parametrize(("coding", "suffix"), [("br", ".br"), ("gzip", ".gz")])
async def test_a_sibling_that_leaves_the_build_is_not_served(tmp_path: Path, coding, suffix):
    """A `<file>.br` symlink planted in the build output pointed outside the
    tree, and was served under the original's name - bytes StaticFiles refuses
    under their own (#978 review). Reachable only with write access to the
    build output, so this is defence in depth. Both codings are checked: the
    guard belongs to the loop over them, not to the first one tried."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"not part of the build" * 50)
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_build(dist)
    asset = dist / "assets" / "escape-AbCdEf12.js"
    asset.write_bytes(b"export const ok = true;\n" * 100)
    (dist / "assets" / f"escape-AbCdEf12.js{suffix}").symlink_to(outside / "secret.txt")
    # A build whose files were landed with `cp -al` or `rsync --link-dest`:
    # every copy has a second name, and every one of them is still served
    # (#978 fourth review).
    linked = dist / "assets" / "linked-AbCdEf12.js"
    linked.write_bytes(b"export const linked = true;\n" * 100)
    linked_copy = dist / "assets" / f"linked-AbCdEf12.js{suffix}"
    linked_copy.write_bytes(_compressed(linked.read_bytes(), coding))
    os.link(linked_copy, tmp_path / f"release-store{suffix}")
    # And a directory that merely looks like a copy must not raise mid-response.
    (dist / "assets" / "weird-AbCdEf12.js").write_bytes(b"export const weird = 1;\n" * 100)
    (dist / "assets" / f"weird-AbCdEf12.js{suffix}").mkdir()

    app = FastAPI()
    configure_frontend(app, dist)

    accept = {"Accept-Encoding": coding}
    escaped = await request(app, "/assets/escape-AbCdEf12.js", headers=accept)
    weird = await request(app, "/assets/weird-AbCdEf12.js", headers=accept)

    hardlinked = await request(app, "/assets/linked-AbCdEf12.js", headers=accept)

    assert escaped[0] == 200 and escaped[2] == asset.read_bytes()
    assert "content-encoding" not in escaped[1]
    assert weird[0] == 200 and "content-encoding" not in weird[1]
    assert hardlinked[0] == 200 and hardlinked[1]["content-encoding"] == coding, (
        "a deploy that hardlinks its build still serves the build's copies"
    )


async def test_a_304_answers_for_the_representation_it_would_have_sent(built_app):
    """The conditional was evaluated against the identity file before a copy
    was chosen, so the 304 carried the identity `ETag` and no `Vary`: a shared
    cache could then hand the Brotli body to a client that asked for none
    (#978 review)."""
    app, _, _ = built_app
    accept = {"Accept-Encoding": "br"}

    _, identity_headers, _ = await request(
        app, "/assets/app-AbCdEf12.js", headers={"Accept-Encoding": "identity"}
    )
    _, brotli_headers, _ = await request(app, "/assets/app-AbCdEf12.js", headers=accept)
    assert identity_headers["etag"] != brotli_headers["etag"]

    status, headers, body = await request(
        app,
        "/assets/app-AbCdEf12.js",
        headers={**accept, "If-None-Match": brotli_headers["etag"]},
    )
    assert (status, body) == (304, b"")
    assert headers["etag"] == brotli_headers["etag"]
    assert "accept-encoding" in headers.get("vary", "").lower()

    # The identity validator does not match the copy the client would get.
    stale, _, _ = await request(
        app,
        "/assets/app-AbCdEf12.js",
        headers={**accept, "If-None-Match": identity_headers["etag"]},
    )
    assert stale == 200

    # An identity answer says so too: the representation varies either way.
    _, plain_headers, _ = await request(
        app, "/assets/app-AbCdEf12.js", headers={"Accept-Encoding": "identity"}
    )
    assert "accept-encoding" in plain_headers.get("vary", "").lower()
    plain_304, plain_304_headers, _ = await request(
        app,
        "/assets/app-AbCdEf12.js",
        headers={"Accept-Encoding": "identity", "If-None-Match": identity_headers["etag"]},
    )
    assert plain_304 == 304
    assert "accept-encoding" in plain_304_headers.get("vary", "").lower()

    # A 304 from the modification time carries `Vary` as well.
    by_time, time_headers, _ = await request(
        app,
        "/assets/app-AbCdEf12.js",
        headers={**accept, "If-Modified-Since": brotli_headers["last-modified"]},
    )
    assert by_time == 304
    assert "accept-encoding" in time_headers.get("vary", "").lower()


@pytest.mark.parametrize("suffix", [".br", ".gz"])
def test_a_fifo_wearing_a_copy_s_name_is_refused_without_opening_it(tmp_path: Path, suffix):
    """Opening a FIFO blocks until somebody writes to it, on a worker thread
    no timeout can cancel: the request never answers and the process needs
    killing. The regular-file check is the only thing that prevents it, and
    nothing tested it (#978 fifth review).

    Asked of `precompressed_variant` directly rather than through a request,
    because a test that proves this by hanging is one CI reports as a timeout
    six hours later rather than as a failure (#978 sixth review).
    """
    from starlette.responses import FileResponse

    from app.compression import precompressed_variant

    asset = tmp_path / "app-AbCdEf12.js"
    asset.write_bytes(b"export const ok = true;\n" * 100)
    os.mkfifo(tmp_path / f"app-AbCdEf12.js{suffix}")
    scope = {
        "type": "http",
        "headers": [(b"accept-encoding", b"br, gzip")],
    }

    assert precompressed_variant(FileResponse(asset), scope) is None


async def test_a_copy_is_refused_under_its_own_name_on_a_case_sensitive_volume(tmp_path: Path):
    """The guard lower-cases the path because APFS and NTFS answer
    `app.js.BR` with the copy. On a case-sensitive volume - which CI uses -
    the request 404s for the ordinary reason, so the guard itself is asked
    here instead (#978 sixth review)."""
    from starlette.exceptions import HTTPException

    from app.main import SPAStaticFiles

    dist = tmp_path / "dist"
    dist.mkdir()
    _write_build(dist)
    files = SPAStaticFiles(directory=dist, html=True)

    for path in ("assets/app-AbCdEf12.js.BR", "assets/app-AbCdEf12.js.Gz"):
        with pytest.raises(HTTPException) as refused:
            await files.get_response(path, {"type": "http", "path": f"/{path}", "headers": []})
        assert refused.value.status_code == 404, path
