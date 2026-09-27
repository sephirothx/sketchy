"""The control-character door (#995), and the secrets it leaves alone."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.bug_reports import BugReportBody
from app.api.errors import install_validation_handler
from app.api.user_settings import UserSettingsPatch
from app.auth.routes import RegistrationBody
from app.handlers.payloads import PayloadError, TextPayload, parse_payload
from app.request_limits import DEFAULT_MAX_BODY_BYTES, RequestSizeLimitMiddleware
from app.request_text import MAX_NESTING_DEPTH, ControlFreeModel


class _Body(ControlFreeModel):
    name: str
    password: str
    current_password: str | None = None
    tags: list[str] = []


class _Loose(ControlFreeModel):
    value: object


def test_text_fields_refuse_control_characters_wherever_they_sit():
    for bad in ({"name": "a\x00b", "password": "ok"}, {"name": "ok", "password": "ok", "tags": ["fine", "b\x1bd"]}):
        with pytest.raises(ValidationError, match="control characters"):
            _Body(**bad)
    assert _Body(name="two\nlines\tand a tab", password="x").name == "two\nlines\tand a tab"


def test_a_password_is_an_opaque_secret_and_is_not_read_as_text():
    """Hashed, never stored, and the key to every proof an account can make:
    a byte the policy accepted must keep opening every door."""
    body = _Body(name="ok", password="long-enough\x1bsecret\x00", current_password="old\x07")
    assert body.password == "long-enough\x1bsecret\x00"
    assert body.current_password == "old\x07"


# ~10 KB of JSON, far inside the 512 KiB body limit, and deeper than the
# interpreter's recursion limit: a recursive walk raised RecursionError on it,
# which a route answered 500 and a socket command crashed its handler on.
DEEP = 5_000


def _nested(depth: int, leaf: object = "x") -> object:
    value = leaf
    for _ in range(depth):
        value = [value]
    return value


def _nested_objects(depth: int) -> dict:
    value: dict = {"leaf": "x"}
    for _ in range(depth):
        value = {"k": value}
    return value


def test_a_deeply_nested_body_is_a_validation_error_not_a_crash():
    deep = _nested(DEEP)
    cases = [
        (UserSettingsPatch, {"theme": deep}),
        (RegistrationBody, {"username": deep, "password": "long-enough-password"}),
        (RegistrationBody, {"username": "ok", "password": "long-enough-password", "settings": {"theme": deep}}),
        (
            BugReportBody,
            {"area": "other", "severity": "low", "summary": "s", "details": "d", "clientContext": _nested_objects(DEEP)},
        ),
    ]
    for model, body in cases:
        with pytest.raises(ValidationError, match="nested too deeply"):
            model.model_validate(body)


def test_the_depth_bound_leaves_every_real_shape_alone():
    """Nothing a screen sends nests more than a few levels; the bound is far past that."""
    at_the_bound = _nested(MAX_NESTING_DEPTH - 1, leaf=[])
    one_past = _nested(MAX_NESTING_DEPTH, leaf=[])

    assert _Loose(value=at_the_bound).value == at_the_bound
    with pytest.raises(ValidationError, match="nested too deeply"):
        _Loose(value=one_past)
    # Still read to the bottom: a control character at the deepest allowed level is found.
    with pytest.raises(ValidationError, match="control characters"):
        _Loose(value=_nested(MAX_NESTING_DEPTH - 1, leaf=["\x00"]))


async def test_a_deeply_nested_request_body_is_answered_422():
    """Through the app's own 422 renderer: FastAPI's default echoes each
    failing value through a recursive encoder, which crashed on the same body
    even once the walk refused it - and on a password, which the walk skips."""
    app = FastAPI()
    install_validation_handler(app)

    @app.patch("/api/users/me/settings")
    async def patch_settings(body: UserSettingsPatch):
        return {"ok": True}

    @app.post("/api/auth/register")
    async def register(body: RegistrationBody):
        return {"ok": True}

    app.add_middleware(RequestSizeLimitMiddleware)
    deep = b"[" * DEEP + b"]" * DEEP
    requests = [
        ("PATCH", "/api/users/me/settings", b'{"theme": ' + deep + b"}", ["body", "theme"]),
        ("POST", "/api/auth/register", b'{"username": "ok", "password": ' + deep + b"}", ["body", "password"]),
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        for method, path, payload, loc in requests:
            assert len(payload) < DEFAULT_MAX_BODY_BYTES
            response = await http.request(
                method, path, content=payload, headers={"content-type": "application/json"}
            )
            assert response.status_code == 422, response.text
            [error] = response.json()["detail"]
            assert error["loc"] == loc
            assert "input" not in error


def test_a_deeply_nested_socket_command_is_an_invalid_payload():
    with pytest.raises(PayloadError):
        parse_payload(TextPayload, {"text": _nested(DEEP)})
