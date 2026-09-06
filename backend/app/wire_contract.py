"""The socket contract as one document, so a change to it is a diff, not a guess.

`tests/test_wire_contract.py` proves both ends use the same *names*. Names are
not the contract: a key can move from one event to another, a field can change
type or stop being required, a tuple can swap two positions, a binary layout
can change under the same tag - and the union of names stays exactly the same.
#567 asked for something a reviewer and CI can compare across revisions.

`build_contract()` assembles that document from the running code, and where
the code cannot be read mechanically, from declarations kept here beside the
reasoning:

* every client command, the rate class it spends (`budgets.py`), and the JSON Schema of its
  payload model - types, bounds, aliases, which fields are required - or, for
  the three hand-written parsers, a declared layout;
* every server event and, for the ones that travel as a tuple, its declared
  positional layout; plus the camelCase keys each payload-building function
  emits, attributed to the function so a key moving between builders shows;
* the refusal codes, the version constants both ends compare, the live-drawing
  frame constants, and a hash of each cross-language fixture.

What it cannot see, and review must: a change of *meaning* under an identical
shape (a field that now holds something else), and privacy - a key that is
still named but now carries what it must not. The document is a floor for
review, not a proof of compatibility.

`fixtures/wire_contract.json` is this document as last committed;
`scripts/check-wire-contract.py` regenerates it, refuses a stale copy, and
compares the tree's contract with the base branch's - see docs/wire-protocol.md
§11 for the policy on when a difference must bump `PROTOCOL_VERSION`.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app import live_drawing
from app.canvas_history import BINARY_HISTORY_MAGIC, CANVAS_HISTORY_VERSION
from app.client_config import CLIENT_CONFIG_CONTRACT_VERSION
from app.handlers import payloads
from app.handlers.budgets import COMMAND_CLASSES, SILENT_COMMANDS, CommandBudgetPolicy
from app.handlers.refusals import ErrorCode
from app.protocol import PROTOCOL_VERSION
from app.services.shutdown import PAUSE_NOTICE_CONTRACT_VERSION, SHUTDOWN_NOTICE_CONTRACT_VERSION

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
FIXTURE_PATH = REPO_ROOT / "fixtures" / "wire_contract.json"

# --- declarations ------------------------------------------------------------

#: Every client command, with the model that parses it. A command whose payload
#: is read by hand names its parser instead; the layout is declared below.
#: `tests/test_wire_contract_baseline.py` checks this against the registered
#: handlers, so a new command cannot be added without saying what it carries.
COMMAND_PAYLOADS: dict[str, type[payloads.RequestModel] | str] = {
    "accept_colorblind_suggestion": payloads.EmptyPayload,
    "add_friend": payloads.AddFriendPayload,
    "become_player": payloads.EmptyPayload,
    "buy_hint": payloads.HintPayload,
    "buy_wheel_letter": payloads.WheelLetterPayload,
    "cast_restart_vote": payloads.RestartVotePayload,
    "create_room": payloads.CreateRoomPayload,
    "dismiss_colorblind_suggestion": payloads.EmptyPayload,
    "draw": "parse_draw_payload",
    "get_custom_prompts": payloads.EmptyPayload,
    "get_recap_drawing": payloads.RecapDrawingPayload,
    "get_room_preview": payloads.RoomPreviewPayload,
    "get_room_settings": payloads.EmptyPayload,
    "guess": payloads.GuessPayload,
    "invite_friend": payloads.FriendUserPayload,
    "join_friend_room": payloads.JoinFriendRoomPayload,
    "join_room": payloads.JoinRoomPayload,
    "leave_room": payloads.EmptyPayload,
    "propose_restart_vote": payloads.EmptyPayload,
    "react_to_drawing": payloads.ReactToDrawingPayload,
    "rename_player": payloads.RenamePlayerPayload,
    "report_player": payloads.ReportPlayerPayload,
    "request_sync_strokes": "parse_sync_request_payload",
    "select_prompt": payloads.SelectPromptPayload,
    "send_chat": payloads.TextPayload,
    "send_lobby_chat": payloads.TextPayload,
    "session_ping": payloads.EmptyPayload,
    "start_game": payloads.EmptyPayload,
    "toggle_afk": payloads.ToggleAfkPayload,
    "undo_stroke": "parse_undo_payload",
    "unwatch_lobby": payloads.EmptyPayload,
    "update_player_settings": payloads.PlayerSettingsPayload,
    "update_room_settings": payloads.UpdateRoomSettingsPayload,
    "vote_player": payloads.VotePayload,
    "watch_lobby": payloads.EmptyPayload,
}

#: Layouts a schema cannot express: positional arrays and the binary frame.
#: Order matters here - that is the point of declaring them.
HAND_PARSED_LAYOUTS: dict[str, Any] = {
    "parse_draw_payload": {
        "arguments": ["frame", "actionIdentity?"],
        "frame": "int header (control actions) | base64 text (<= MAX_BASE64_FRAME_BYTES) | binary attachment",
        "actionIdentity": ["generation", "sequence"],
        "identityOn": sorted(["draw_start", "draw_shape", "draw_fill", "clear_canvas"]),
    },
    "parse_sync_request_payload": {
        "argument": "null | [generation, heldActionCount, historyHash]",
    },
    "parse_undo_payload": {
        "argument": ["generation", "sequence", "revision", "historyHash"],
    },
}

#: Server events whose payload is positional. Everything else is an object,
#: whose keys are read from the code below.
TUPLE_EVENTS: dict[str, list[str]] = {
    "draw": ["frame", "commit?[generation, sequence, revision, historyHash]"],
    "canvas_commit": ["generation", "sequence", "revision", "historyHash"],
    "canvas_reset": ["revision", "generation", "sequence", "historyHash"],
    "canvas_undo": ["generation", "sequence", "revisionBefore", "revisionAfter", "historyHash"],
    "sync_strokes": ["binaryHistory", "revision", "generation", "sequence", "historyHash"],
    "sync_strokes_tail": ["binaryTail", "baseActionCount", "revision", "generation", "sequence", "historyHash"],
    "request_canvas_actions": ["generation", "expectedSequence", "receivedSequence"],
}

#: Events no scan can see: `main.py` hands `("account_suspended", payload)` to a
#: helper that emits it. Declared rather than special-cased in the extractor,
#: and the baseline test checks the whole list against wire §5.
DECLARED_EVENTS = frozenset({"account_suspended"})

#: Acknowledgements that deliberately do not take the refusal shape (wire §2).
ACK_EXCEPTIONS: dict[str, str] = {
    "guess": "bare receipt, no body",
    "session_ping": "[1, phaseCode, round, remaining, generation, sequence] | [0]",
    "draw": "no acknowledgement; a throttled frame answers nothing",
}

#: Cross-language fixtures whose bytes pin a binary layout or an event shape.
PINNED_FIXTURES = (
    "fixtures/canvas_protocol_v1.json",
    "fixtures/lobby_presence_v1.json",
    "fixtures/stored_drawings_v1.json",
)

CAMEL_CASE = re.compile(r"[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*")
BUILTIN_EVENTS = frozenset({"connect", "disconnect", "connect_error"})
#: Modules whose dict keys and emits are not the server's: `probe` speaks *to* a
#: server, and this module describes one.
EXCLUDED_MODULES = frozenset({"probe", "wire_contract"})

# --- extraction --------------------------------------------------------------


def _string_arg(node: ast.Call, index: int) -> str | None:
    if len(node.args) > index and isinstance(node.args[index], ast.Constant):
        value = node.args[index].value
        return value if isinstance(value, str) else None
    return None


def _emitted_events(trees: dict[str, ast.Module]) -> list[str]:
    """Event names passed to `emit`, plus those first bound to a name ending in
    `event`/`event_name` and emitted through it - `event = "canvas_undo"`.

    `tests/test_wire_contract_baseline.py` compares the result with the table
    in docs/wire-protocol.md §5, so an emit this cannot see is caught there.
    """
    names: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "emit":
                name = _string_arg(node, 0)
                if name:
                    names.add(name)
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and (t.id == "event" or t.id.endswith("event_name")) for t in node.targets
            ):
                for constant in ast.walk(node.value):
                    if isinstance(constant, ast.Constant) and isinstance(constant.value, str) and re.fullmatch(r"[a-z_]+", constant.value):
                        names.add(constant.value)
    return sorted((names | DECLARED_EVENTS) - BUILTIN_EVENTS)


def _payload_builders(trees: dict[str, ast.Module]) -> dict[str, list[str]]:
    """camelCase keys by the function that writes them: `module:function`."""
    builders: dict[str, set[str]] = {}
    for module, tree in trees.items():
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            keys: set[str] = set()
            for node in ast.walk(function):
                if isinstance(node, ast.Dict):
                    for key in node.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str) and CAMEL_CASE.fullmatch(key.value):
                            keys.add(key.value)
            if keys:
                builders.setdefault(f"{module}:{function.name}", set()).update(keys)
    return {name: sorted(keys) for name, keys in sorted(builders.items())}


def _module_trees() -> dict[str, ast.Module]:
    trees = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        module = str(path.relative_to(APP_DIR)).removesuffix(".py").replace("/", ".")
        if module in EXCLUDED_MODULES:
            continue
        trees[module] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return trees


def _schema(model: type[payloads.RequestModel]) -> dict:
    schema = model.model_json_schema(by_alias=True)
    schema.pop("title", None)
    return schema


def _fixture_digest(relative: str) -> str:
    return hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()


def build_contract() -> dict[str, Any]:
    """The contract of the tree this code was imported from."""
    trees = _module_trees()
    policy = CommandBudgetPolicy()
    commands = {}
    for name, parser in sorted(COMMAND_PAYLOADS.items()):
        entry: dict[str, Any] = {"commandClass": policy.class_of(name), "silent": name in SILENT_COMMANDS}
        if isinstance(parser, str):
            entry["parser"] = parser
            entry["layout"] = HAND_PARSED_LAYOUTS[parser]
        else:
            entry["payload"] = _schema(parser)
        if name in ACK_EXCEPTIONS:
            entry["acknowledgement"] = ACK_EXCEPTIONS[name]
        commands[name] = entry
    events = {}
    for name in _emitted_events(trees):
        events[name] = {"layout": TUPLE_EVENTS[name]} if name in TUPLE_EVENTS else {"shape": "object"}
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "versions": {
            "LIVE_DRAWING_VERSION": live_drawing.LIVE_DRAWING_VERSION,
            "CANVAS_HISTORY_VERSION": CANVAS_HISTORY_VERSION,
            "CLIENT_CONFIG_CONTRACT_VERSION": CLIENT_CONFIG_CONTRACT_VERSION,
            "SHUTDOWN_NOTICE_CONTRACT_VERSION": SHUTDOWN_NOTICE_CONTRACT_VERSION,
            "PAUSE_NOTICE_CONTRACT_VERSION": PAUSE_NOTICE_CONTRACT_VERSION,
        },
        "liveDrawing": {
            "magic": BINARY_HISTORY_MAGIC.decode(),
            "maxBase64FrameBytes": live_drawing.MAX_BASE64_FRAME_BYTES,
            "maxPointsPerFrame": live_drawing.MAX_POINTS_PER_FRAME,
            "tags": {
                "path_start": live_drawing.PATH_START_TAG,
                "path_points": live_drawing.PATH_POINTS_TAG,
                "path_end": live_drawing.PATH_END_TAG,
                "shape": live_drawing.SHAPE_TAG,
                "fill": live_drawing.FILL_TAG,
                "clear": live_drawing.CLEAR_TAG,
                "path_points_delta": live_drawing.PATH_POINTS_DELTA_TAG,
            },
        },
        "refusal": {"shape": ["ok", "errorCode", "error", "field?", "retryAfterMs?"], "codes": [c.value for c in ErrorCode]},
        "commands": commands,
        "events": events,
        "payloadBuilders": _payload_builders(trees),
        "fixtures": {relative: _fixture_digest(relative) for relative in PINNED_FIXTURES},
        "commandClasses": sorted({policy.class_of(c) for c in COMMAND_PAYLOADS} | set(COMMAND_CLASSES.values())),
    }


# --- comparison --------------------------------------------------------------


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return out or {prefix: {}}
    return {prefix: value}


def diff_contracts(base: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Every leaf that differs, as `path: base -> current` lines."""
    before, after = _flatten(base), _flatten(current)
    lines = []
    for path in sorted(set(before) | set(after)):
        if path == "protocolVersion":
            continue
        if path not in before:
            lines.append(f"+ {path}: {json.dumps(after[path])}")
        elif path not in after:
            lines.append(f"- {path}: {json.dumps(before[path])}")
        elif before[path] != after[path]:
            lines.append(f"~ {path}: {json.dumps(before[path])} -> {json.dumps(after[path])}")
    return lines


def bump_missing(base: dict[str, Any], current: dict[str, Any]) -> bool:
    """A contract that moved under a version that did not."""
    return bool(diff_contracts(base, current)) and current.get("protocolVersion") == base.get("protocolVersion")


def dumps(contract: dict[str, Any]) -> str:
    return json.dumps(contract, indent=1, sort_keys=True) + "\n"
