"""A ceiling on how much request body this server will hold in memory.

Nothing bounded it before. That was survivable while every endpoint took a
small JSON object, but a bug report can legitimately carry a screenshot, and
the moment one route invites megabytes the absence of a limit becomes the
limit. Sketchy runs a single worker by design (N-01), so one oversized body is
one process's memory.

Two layers, because there are two ways a body arrives:

* A declared `Content-Length` over the cap is refused before the application is
  invoked at all - no routing, no session lookup, nothing read. This is what
  every ordinary client and every realistic attacker produces.
* A body that arrives without a length, or with one that lies, is counted as it
  streams and cut off at the cap. The handler then sees a truncated body and
  fails its own validation. Truncation rather than a tidy 413 is the deliberate
  trade: the response is the application's to write by then, and bounding the
  memory is the part that matters.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping


# Sized against the largest body the API actually declares: a prompt list is
# 500 prompts, each with up to 20 aliases, which is a few hundred kilobytes of
# legitimate JSON. `test_request_limits.py` derives that worst case from the
# domain constants and fails if this stops covering it, so raising a prompt
# limit cannot quietly start rejecting saves.
DEFAULT_MAX_BODY_BYTES = 512 * 1024

# A screenshot is capped at 2 MiB decoded, which is about 2.8 MB of base64,
# and it travels inside a JSON object that also carries up to 32 KiB of
# context. Four gives that room without inviting anything else.
BUG_REPORT_MAX_BODY_BYTES = 4 * 1024 * 1024

# A picture is 128 KiB decoded, about 175 KB of base64, in a JSON envelope.
AVATAR_MAX_BODY_BYTES = 256 * 1024
PATH_LIMITS: Mapping[str, int] = {
    "/api/bug-reports": BUG_REPORT_MAX_BODY_BYTES,
    "/api/users/me/avatar": AVATAR_MAX_BODY_BYTES,
}


class RequestSizeLimitMiddleware:
    """Pure ASGI, deliberately.

    `BaseHTTPMiddleware` reads the request to hand it on, which would buffer
    exactly the body this exists to refuse.
    """

    def __init__(
        self,
        app,
        *,
        default_max_bytes: int = DEFAULT_MAX_BODY_BYTES,
        path_limits: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self._default = default_max_bytes
        self._paths = dict(path_limits if path_limits is not None else PATH_LIMITS)

    def limit_for(self, path: str) -> int:
        return self._paths.get(path, self._default)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.limit_for(scope.get("path", ""))
        declared = _declared_length(scope.get("headers") or ())
        if declared is not None and declared > limit:
            await _refuse(send, limit)
            return

        await self.app(scope, _counted(receive, limit), send)


def _declared_length(headers) -> int | None:
    for name, value in headers:
        if name.lower() != b"content-length":
            continue
        try:
            return int(value)
        except ValueError:
            # A malformed length is not a promise about anything; the streaming
            # count below is what decides.
            return None
    return None


def _counted(receive: Callable[[], Awaitable[dict]], limit: int):
    """Wrap `receive` so the body it yields cannot exceed `limit`."""
    seen = 0

    async def guarded() -> dict:
        nonlocal seen
        message = await receive()
        if message.get("type") != "http.request":
            return message
        body = message.get("body", b"")
        seen += len(body)
        if seen > limit:
            # Cut the body short and declare it finished. The handler sees an
            # incomplete payload and rejects it, which is the outcome an
            # oversized request deserves and costs no more memory to reach.
            return {"type": "http.request", "body": b"", "more_body": False}
        return message

    return guarded


async def _refuse(send, limit: int) -> None:
    body = (
        b'{"detail":"That request is too large. The limit is '
        + str(limit).encode()
        + b' bytes."}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
