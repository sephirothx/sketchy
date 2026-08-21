"""The socket contract between this server and the bundled client.

Nothing in either language checks that the two sides agree on a name. A rename
on one side of the boundary type-checks, lints, and passes every unit test,
because the payload key is a plain string here and a plain property there - the
mismatch only shows up as a feature that silently stops working. That is exactly
how ``maskedWord`` briefly became ``maskedPrompt`` on the client alone (#310),
leaving the drawing phase reading ``undefined``.

So this suite pins the four things the two sides have to agree on: the events
each direction sends, the camelCase keys the server puts in its payloads, and
the field names its command parsers accept. It reads both trees as text rather
than running them, which keeps it fast and dependency-free; the cost is that it
matches identifiers, not semantics.

Renaming a wire name is still fine - rename it on both sides in one change, and
this suite goes quiet. That is the whole point: it does not forbid renames, it
forbids half of one.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_APP = REPO_ROOT / "backend" / "app"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# Socket.IO's own lifecycle events, plus the acknowledgement fields every
# command reply shares. Neither is part of the game vocabulary.
BUILTIN_EVENTS = {"connect", "disconnect", "connect_error"}
ACK_FIELDS = {"ok", "error", "field"}


def _python_sources() -> list[ast.Module]:
    return [
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(BACKEND_APP.rglob("*.py"))
    ]


def _frontend_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(FRONTEND_SRC.rglob("*.ts*"))
    )


def _string_arg(node: ast.Call, index: int) -> str | None:
    if len(node.args) <= index:
        return None
    arg = node.args[index]
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None


def _calls_named(trees: list[ast.Module], attr: str) -> list[ast.Call]:
    found: list[ast.Call] = []
    for tree in trees:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == attr
            ):
                found.append(node)
    return found


@pytest.fixture(scope="module")
def trees() -> list[ast.Module]:
    return _python_sources()


@pytest.fixture(scope="module")
def frontend() -> str:
    return _frontend_text()


def _wire_alias(statement: ast.AnnAssign) -> str | None:
    """The `alias=` of a `Field(...)` default, if the field declares one."""
    default = statement.value
    if not isinstance(default, ast.Call) or getattr(default.func, "id", None) != "Field":
        return None
    for keyword in default.keywords:
        if keyword.arg == "alias" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def _mentions(frontend: str, name: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", frontend) is not None


def test_server_payload_keys_are_read_by_the_client(trees, frontend):
    """Every camelCase key the server sends must be named in the client.

    Python dict keys are snake_case by convention, so a camelCase string key is
    a wire name by construction.
    """
    keys: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if re.fullmatch(r"[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*", key.value):
                        keys.add(key.value)

    assert keys, "found no camelCase payload keys - has the extraction broken?"
    unread = sorted(key for key in keys if not _mentions(frontend, key))
    assert not unread, (
        "the server sends payload keys the client never names: "
        f"{unread}. Either the client reads a different name (a half-finished "
        "rename), or the key is dead and should be dropped."
    )


def test_command_parser_fields_are_sent_by_the_client(trees, frontend):
    """Every field a command parser accepts must be named in the client.

    Catches the mirror case: renaming an inbound field on the server while the
    client keeps sending the old one.
    """
    # RequestModel and everything deriving from it, however deep - payload
    # classes inherit shared field groups rather than always deriving directly.
    json_commands = {"RequestModel"}
    for _ in range(8):
        for tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(
                    isinstance(base, ast.Name) and base.id in json_commands for base in node.bases
                ):
                    json_commands.add(node.name)

    fields: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            # Only the JSON commands. The binary drawing protocol carries
            # positional frames, so its dataclass field names are internal.
            if not isinstance(node, ast.ClassDef) or node.name not in json_commands:
                continue
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign) or not isinstance(
                    statement.target, ast.Name
                ):
                    continue
                # A Field(alias=...) renames the field on the wire; the alias is
                # what the client actually sends.
                fields.add(_wire_alias(statement) or statement.target.id)

    assert fields, "found no command payload fields - has the extraction broken?"
    unsent = sorted(
        field
        for field in fields
        if not field.startswith("_") and field not in ACK_FIELDS and not _mentions(frontend, field)
    )
    assert not unsent, (
        "command parsers accept fields the client never names: "
        f"{unsent}. Either the client sends a different name, or the field is "
        "dead and should be dropped."
    )


def test_client_commands_are_registered_on_the_server(trees, frontend):
    """Every event the client emits must have a handler registered for it."""
    registered = {
        name
        for call in _calls_named(trees, "on")
        if (name := _string_arg(call, 0)) is not None
    } | BUILTIN_EVENTS

    # socket.emit("cmd", ...), emitWithAck("cmd", ...), and the runAction
    # wrapper, which takes the event as its second argument.
    text = _frontend_text()
    emitted = (
        set(re.findall(r"\.emit\(\s*\"([a-z_]+)\"", text))
        | set(re.findall(r"emitWithAck(?:<[^>]*>)?\(\s*\"([a-z_]+)\"", text))
        | set(re.findall(r"runAction\([^,]+,\s*\"([a-z_]+)\"", text))
    )
    assert emitted, "found no client emits - has the extraction broken?"

    unhandled = sorted(emitted - registered)
    assert not unhandled, (
        f"the client emits commands the server does not register: {unhandled}"
    )


def test_server_events_are_listened_for_by_the_client(trees, frontend):
    """Every event the server emits must have a listener on the client."""
    emitted = {
        name
        for call in _calls_named(trees, "emit")
        if (name := _string_arg(call, 0)) is not None
    } - BUILTIN_EVENTS

    listened = set(re.findall(r"\.on\(\s*\"([a-z_]+)\"", _frontend_text())) | BUILTIN_EVENTS
    assert emitted, "found no server emits - has the extraction broken?"

    unheard = sorted(emitted - listened)
    assert not unheard, (
        f"the server emits events the client never listens for: {unheard}"
    )
