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

Passwords are the exception. They are opaque secrets, hashed on arrival and
never stored or compared as text, so the database never sees a byte of one;
and a password is checked at every proof - sign-in, change, second-factor
enrolment, deletion - so refusing a byte the policy once accepted would lock
its owner out of every door at once, the recovery link included.

The walk is iterative and bounded at :data:`MAX_NESTING_DEPTH`. It used to
recurse, and a body five thousand lists deep - ten kilobytes, inside every
body limit - raised RecursionError in the validator: a 500 on every route with
a body. Past the bound the value is refused like a control character, as a
validation failure naming its field.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator

CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

CONTROL_CHARACTER_MESSAGE = "Text must not contain control characters"

# Fields that carry a secret rather than text: hashed, never stored, and the
# key to every proof an account can make (see the module docstring).
SECRET_FIELDS = frozenset({"password", "current_password"})

# How many lists and objects deep a field's value may nest. Nothing a screen
# sends goes past four - a prompt list's entries and their aliases, a bug
# report's recent errors - so thirty-two refuses no real request. The bound is
# what keeps a hostile one cheap: ten kilobytes of brackets is five thousand
# levels, inside every body limit, and a recursive walk over it raised
# RecursionError, which a route answered 500 and a socket handler crashed on.
MAX_NESTING_DEPTH = 32

NESTING_MESSAGE = "Value is nested too deeply"


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
    """Refuse a control character anywhere in `value`, or nesting past the bound.

    Iterative, with the depth carried beside each value, so no input can reach
    the interpreter's recursion limit and the refusal is a ``ValueError`` -
    a validation failure naming the field - rather than a crash.
    """
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, str):
            reject_control_characters(item)
            continue
        if isinstance(item, dict):
            children = [part for pair in item.items() for part in pair]
        elif isinstance(item, (list, tuple, set, frozenset)):
            children = list(item)
        else:
            continue
        if depth >= MAX_NESTING_DEPTH:
            raise ValueError(NESTING_MESSAGE)
        pending.extend((child, depth + 1) for child in children)


class ControlFreeModel(BaseModel):
    """A request model whose every string, however nested, is control-free.

    Runs before the field's own validation, on the raw value, so a model that
    later strips, lowercases or parses its text never sees the character and
    the refusal names the field it arrived in.
    """

    @field_validator("*", mode="before")
    @classmethod
    def _refuse_control_characters(cls, value: Any, info: ValidationInfo) -> Any:
        if info.field_name in SECRET_FIELDS:
            return value
        _walk(value)
        return value
