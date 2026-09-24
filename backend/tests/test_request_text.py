"""The control-character door (#995), and the secrets it leaves alone."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.request_text import ControlFreeModel


class _Body(ControlFreeModel):
    name: str
    password: str
    current_password: str | None = None
    tags: list[str] = []


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
