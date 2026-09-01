"""The socket contract between this server and the bundled client.

Nothing in either language checks that the two sides agree on a name. A rename
on one side of the boundary type-checks, lints, and passes every unit test,
because the payload key is a plain string here and a plain property there - the
mismatch only shows up as a feature that silently stops working. That is exactly
how ``maskedPrompt`` briefly became ``maskedPrompt`` on the client alone (#310),
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
import json
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
EXPORT_CONTRACT = json.loads(
    (REPO_ROOT / "fixtures" / "account_data_export_v2_fields.json").read_text(
        encoding="utf-8"
    )
)
EXPORT_DOWNLOAD_FIELDS = {
    path.rsplit(".", 1)[-1].removeprefix("[]")
    for path in EXPORT_CONTRACT["fieldPaths"]
}


def test_both_ends_agree_on_the_protocol_version():
    """A version bumped on one side only is worse than no version at all.

    The client sends its number at the handshake and the server answers a
    mismatch with `upgrade_required`, which the client obeys by reloading - so
    a backend bumped alone puts every client into a reload loop, and a
    frontend bumped alone silently asks everyone to reload for ever.
    """
    backend = re.search(
        r"^PROTOCOL_VERSION = (\d+)$",
        (BACKEND_APP / "protocol.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    frontend = re.search(
        r"^export const PROTOCOL_VERSION = (\d+);$",
        (FRONTEND_SRC / "lib" / "protocol.ts").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert backend and frontend, "the protocol version has moved - update this test"
    assert backend.group(1) == frontend.group(1), (
        "backend/app/protocol.py says "
        f"{backend.group(1)} and frontend/src/lib/protocol.ts says "
        f"{frontend.group(1)}"
    )


def _diagnostic_blob_keys() -> set[str]:
    """Keys of the bug-report diagnostics blob, which no client parses.

    `_live_room_context` describes the reporter's seat for a human or a model
    to read on the triage page; the client renders it generically, key by key,
    and never names one. Derived from the function rather than listed here so
    that adding a diagnostic cannot silently widen the exemption to the rest of
    the module - a camelCase key anywhere else in that file is still a wire
    name and still has to be read.
    """
    tree = ast.parse(
        (BACKEND_APP / "api" / "bug_reports.py").read_text(encoding="utf-8")
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_live_room_context":
            return {
                key.value
                for inner in ast.walk(node)
                if isinstance(inner, ast.Dict)
                for key in inner.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError("_live_room_context has moved - update this exemption")


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
    # A data export is downloaded as an opaque artifact rather than parsed by
    # the browser. Its v1 field surface is pinned by a dedicated checked-in
    # contract and generation test instead of this live client/server check.
    opaque = EXPORT_DOWNLOAD_FIELDS | _diagnostic_blob_keys()
    unread = sorted(
        key for key in keys if key not in opaque and not _mentions(frontend, key)
    )
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

# Names the glossary retired. `word` is never the entity - the thing being drawn
# is a prompt, and a third of the shipped ones are more than one word - and
# `round` names a full rotation, so only a genuine round count may carry it.
RETIRED = {
    "answer",
    "artist",
    "budget",
    "colour",
    "leaderboard",
    "observer",
    "resume",
    "scoreboard",
    "solution",
    "viewer",
    "word",
}
ROUND_EXCEPTIONS = {"roundNumber", "totalRounds", "rounds", "round_number", "total_rounds"}


def _uses_retired_vocabulary(name: str) -> bool:
    lowered = re.sub(r"[^a-z]", " ", re.sub(r"(?<!^)([A-Z])", r" \1", name).lower())
    tokens = set(lowered.split())
    if tokens & RETIRED:
        return True
    return "round" in tokens and name not in ROUND_EXCEPTIONS


def test_wire_names_use_the_current_vocabulary(trees, frontend):
    """No wire name may carry a word the glossary retired.

    The checks above only prove the two sides agree. They stay green when both
    keep an old name, which is how `select_prompt` shipped carrying a `word`
    field: consistent, and still the wrong noun. This is the check that says so.

    See GLOSSARY.md. Adding a name here is a decision to make deliberately, not
    a failure to route around.
    """
    names: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                names |= {
                    key.value
                    for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
            elif isinstance(node, ast.ClassDef) and node.name.endswith("Payload"):
                for statement in node.body:
                    if isinstance(statement, ast.AnnAssign) and isinstance(
                        statement.target, ast.Name
                    ):
                        names.add(_wire_alias(statement) or statement.target.id)
    for call in _calls_named(trees, "emit") + _calls_named(trees, "on"):
        if (event := _string_arg(call, 0)) is not None:
            names.add(event)

    stale = sorted(name for name in names if _uses_retired_vocabulary(name))
    assert not stale, (
        f"wire names still using retired vocabulary: {stale}. The thing being "
        "drawn is a prompt; a round is a full rotation of turns. See GLOSSARY.md."
    )


def test_player_facing_copy_uses_current_vocabulary():
    """Keep the exact retired phrases that previously drifted out of UI and docs."""
    sources = [REPO_ROOT / "README.md", *sorted(FRONTEND_SRC.rglob("*.ts*"))]
    text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    retired_phrases = {
        "Brush Tool",
        "Claim my name",
        "Claim your name",
        "Download drawing",
        "Game Settings",
        "Game complete",
        "Keyboard Shortcuts",
        "Play again",
        "Reset Defaults",
        "Room rules",
        "View rules",
        "You’re offline",
        'placeholder="Your name"',
        "hint budget",
        "hint debt",
        "leaderboard",
        "name colour",
    }
    stale = sorted(phrase for phrase in retired_phrases if phrase in text)
    assert not stale, f"player-facing copy still uses retired vocabulary: {stale}"


# A suspension lifted, a block made or removed: three writers named a user in
# `target_user_id` and left the ledger's Subject column empty, because the pair
# was added to `audit_events` after they were written and nothing made them
# say so. Reading the source is how that class of omission gets caught, since
# each one only shows up in the one screen nobody looks at until they need it.
def test_every_audit_event_about_somebody_names_them_as_its_subject(trees):
    """`target_user_id` is a foreign key that a deletion blanks; the generic
    pair is what the ledger renders. An entry with one and not the other is an
    action against a person that the ledger cannot show."""
    missing: list[str] = []
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func
            if not (isinstance(name, ast.Name) and name.id == "AuditEvent"):
                continue
            supplied = {kw.arg for kw in node.keywords}
            if "target_user_id" not in supplied:
                # A bulk action - a retention purge - acts on no single row and
                # correctly names nobody.
                continue
            if "target_type" in supplied and "target_id" in supplied:
                continue
            event = next(
                (
                    ast.unparse(kw.value)
                    for kw in node.keywords
                    if kw.arg == "event_type"
                ),
                "<unknown>",
            )
            missing.append(event)

    assert not missing, (
        "these audit events name a user in target_user_id but leave the "
        f"ledger's subject empty: {sorted(missing)}"
    )
