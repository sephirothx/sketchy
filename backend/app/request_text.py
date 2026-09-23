"""The one rule every player-authored string obeys before anything reads it.

PostgreSQL refuses U+0000 in ``text`` (``CharacterNotInRepertoireError``), and a
string that passed every length check and reached a statement with one in it
fails that statement - and everything batched with it. One chat line with a
NUL used to drop the retention batch of up to a hundred other lines, a room
name with one made the finished game unsaveable, and a bug report with one
answered 500. SQLite accepts the byte, so the test suite never met any of it
(#995).

So the rule lives in one place and is applied at the door: every Socket.IO
command model and every REST body descends from :class:`ControlFreeModel`,
which walks each field's raw value - strings, and strings inside lists and
objects - and refuses a C0 control other than tab, newline and carriage
return, plus DEL. Those three are kept because a description or a report's
details legitimately span lines; nothing a keyboard produces needs the rest.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, field_validator

CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

CONTROL_CHARACTER_MESSAGE = "Text must not contain control characters"


def has_control_characters(value: str) -> bool:
    return CONTROL_CHARACTER.search(value) is not None


def reject_control_characters(value: str) -> str:
    """Return `value`, or raise ``ValueError`` when it carries a control character.

    For query parameters and the few strings that do not arrive through a
    model; the models get the same check from :class:`ControlFreeModel`.
    """
    if has_control_characters(value):
        raise ValueError(CONTROL_CHARACTER_MESSAGE)
    return value


def _walk(value: Any) -> None:
    if isinstance(value, str):
        reject_control_characters(value)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _walk(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk(key)
            _walk(item)


class ControlFreeModel(BaseModel):
    """A request model whose every string, however nested, is control-free.

    Runs before the field's own validation, on the raw value, so a model that
    later strips, lowercases or parses its text never sees the character and
    the refusal names the field it arrived in.
    """

    @field_validator("*", mode="before")
    @classmethod
    def _refuse_control_characters(cls, value: Any) -> Any:
        _walk(value)
        return value
