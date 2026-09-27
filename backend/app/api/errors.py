"""The refused HTTP response, in the one shape the client reads.

The socket has answered refusals with an enumerated `errorCode` since #565.
REST answered with prose: `HTTPException(detail="Sign in first.")`, 237 times
across `app/api` and `app/auth`, and a client that wanted to *do* something
about a refusal had only the status and the sentence to go on. So the sentence
was rendered, which made the server the author of text a player reads - and
made translating the interface impossible without translating the server
(#760, R-I18N-01).

A refusal now looks like the acknowledgement it is the HTTP twin of:

    {"errorCode": "sign_in_required", "detail": "...", "field"?: ..., "params"?: {...}}

`detail` stays, unchanged and English, for three readers that are not the
player: a log line, an operator reading a response by hand, and the bug report
a player attaches to a complaint. Nothing renders it (`test_rest_refusals.py`
holds the client to that). `params` carries **values, never fragments** - a
count, a limit, a field name - because a server-built noun phrase dropped into
a client sentence is prose with extra steps, and it breaks in the first
language that inflects.

`Refusal` subclasses `HTTPException` on purpose rather than replacing it: the
static-file fallback in `main.py`, the security middleware and every existing
test go on catching `HTTPException`, and a route that has not been converted
still works. What the subclass adds is a code, and a handler that puts it in
the body.

Staff-only routes keep raising plain `HTTPException` - the moderation queue and
the operations pages are read by operators, in one language, and an audit trail
that reads differently depending on who opened it is worse than one that is
always English.
"""
from __future__ import annotations

from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.refusals import ErrorCode

__all__ = ["Refusal", "install_refusal_handler", "install_validation_handler"]


class Refusal(HTTPException):
    """An HTTP refusal that names its reason.

    `detail` is optional and defaults to the code itself. A caller with nothing
    useful to add should leave it out rather than invent a sentence nobody
    reads: the client writes the player's one.
    """

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        detail: str | None = None,
        *,
        field: str | None = None,
        params: Mapping[str, Any] | None = None,
        retry_after_ms: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=detail if detail is not None else str(code),
            headers=dict(headers) if headers else None,
        )
        self.code = code
        self.field = field
        self.params = dict(params) if params else None
        self.retry_after_ms = retry_after_ms

    def body(self) -> dict[str, Any]:
        """The response body, in key order: what it is, then why, then where."""
        payload: dict[str, Any] = {"errorCode": str(self.code), "detail": self.detail}
        if self.field is not None:
            payload["field"] = self.field
        if self.params is not None:
            payload["params"] = self.params
        if self.retry_after_ms is not None:
            payload["retryAfterMs"] = self.retry_after_ms
        return payload


def install_refusal_handler(api: FastAPI) -> None:
    """Render `Refusal` with its code, and everything else as FastAPI does.

    Registered for the subclass alone, so an unconverted route keeps its
    `{"detail": ...}` body and nothing has to be converted in one go.
    """

    @api.exception_handler(Refusal)
    async def _render(_request: Request, exc: Refusal) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.body(),
            headers=exc.headers,
        )


def install_validation_handler(api: FastAPI) -> None:
    """Render a request that failed validation as FastAPI does, minus its input.

    FastAPI's own handler echoes each failing value back as `input`, through
    `jsonable_encoder`, which recurses: a field sent five thousand lists deep -
    ten kilobytes, inside every body limit - raised RecursionError while the
    422 was being written, and the refusal became a 500. The value is the
    caller's own, so echoing it tells them nothing; `type`, `loc` and `msg`
    are what a 422 is read for, and they keep FastAPI's shape.
    """

    @api.exception_handler(RequestValidationError)
    async def _render(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {key: value for key, value in error.items() if key != "input"}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})
