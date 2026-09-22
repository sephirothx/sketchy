"""What the server compresses on its own loop, and what it serves already compressed.

The frontend build writes a Brotli and a gzip copy beside every text asset
(`frontend/vite.config.ts`), so a script or stylesheet is compressed once, at
build time, at the highest settings - not again for every client on the loop
every room shares. Compressing the 1.7 MB bundle at gzip level 9 cost ~40 ms of
loop CPU per cold page load, in chunks long enough to show up as stroke jitter,
and a deploy is exactly when every client cold-loads at once (#978).

What is left to compress on the fly - API responses, and a stored drawing
frame - is compressed at level 4: about four times cheaper than 9 for a few
per cent more bytes. Images and fonts are never compressed at all: they are
compressed formats already, and a second pass only spends the time to make
them slightly larger.
"""
from __future__ import annotations

import os

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipMiddleware, GZipResponder, IdentityResponder
from starlette.responses import FileResponse, Response
from starlette.types import Message, Receive, Scope, Send

DYNAMIC_COMPRESSLEVEL = 4

# Formats that are compressed already; compressing them again is pure cost.
INCOMPRESSIBLE_CONTENT_TYPES = ("image/", "font/", "audio/", "video/")

# Best first. A sibling is `<file><suffix>`, written by the frontend build.
PRECOMPRESSED_SIBLINGS = (("br", ".br"), ("gzip", ".gz"))


def accepted_encodings(header: str | None) -> set[str]:
    """The content codings an `Accept-Encoding` header admits.

    A coding named with `q=0` is refused rather than accepted - the one case
    where naive substring matching gets the answer backwards.
    """
    accepted: set[str] = set()
    for part in (header or "").split(","):
        coding, _, params = part.strip().partition(";")
        coding = coding.strip().lower()
        if not coding:
            continue
        quality = 1.0
        for param in params.split(";"):
            name, _, value = param.strip().partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality > 0:
            accepted.add(coding)
    return accepted


def precompressed_variant(response: Response, scope: Scope) -> FileResponse | None:
    """The build's compressed copy of `response`'s file, if the client takes one.

    Returns a response for the sibling carrying the original's media type and
    caching headers, with `Content-Encoding` set - which is also what makes the
    compression middleware pass it through untouched. The sibling's own size
    and modification time give it its own validators, so a conditional request
    is answered against the bytes it would actually receive.
    """
    if not isinstance(response, FileResponse):
        return None
    accepted = accepted_encodings(Headers(scope=scope).get("accept-encoding"))
    for coding, suffix in PRECOMPRESSED_SIBLINGS:
        if coding not in accepted:
            continue
        sibling = f"{response.path}{suffix}"
        try:
            stat_result = os.stat(sibling)
        except OSError:
            continue
        variant = FileResponse(
            sibling,
            stat_result=stat_result,
            media_type=response.media_type,
        )
        variant.headers["Content-Encoding"] = coding
        variant.headers.add_vary_header("Accept-Encoding")
        return variant
    return None


class SelectiveGZipMiddleware(GZipMiddleware):
    """Starlette's gzip at a cheaper level, and never for compressed formats."""

    def __init__(self, app, minimum_size: int = 500) -> None:
        super().__init__(app, minimum_size=minimum_size, compresslevel=DYNAMIC_COMPRESSLEVEL)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - websockets pass through
            await self.app(scope, receive, send)
            return
        # Parsed rather than substring-matched, as the parent does, so that
        # `gzip;q=0` means no gzip.
        if "gzip" in accepted_encodings(Headers(scope=scope).get("accept-encoding")):
            responder = _SelectiveGZipResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )
        else:
            responder = IdentityResponder(self.app, self.minimum_size)
        await responder(scope, receive, send)


class _SelectiveGZipResponder(GZipResponder):
    async def send_with_compression(self, message: Message) -> None:
        await super().send_with_compression(message)
        if message["type"] == "http.response.start":
            content_type = MutableHeaders(raw=message["headers"]).get("content-type", "")
            if content_type.startswith(INCOMPRESSIBLE_CONTENT_TYPES):
                self.content_type_is_excluded = True
