"""The structured socket contract: current, complete, and sensitive to what
the name-only checks cannot see (#567).

`test_wire_contract.py` proves both ends use the same names. These tests prove
the *document* `app/wire_contract.py` builds moves when a shape moves - a
field's type, a key's owner, a tuple's order, a binary fixture's bytes - and
that the tracked copy is the tree's. The base-branch comparison itself runs in
`scripts/check-wire-contract.py`; here its two decisions are pinned: a bump
makes any change acceptable, and a regenerated fixture under the same version
is still a change.
"""
from __future__ import annotations

import ast
import copy
import json
import re
from pathlib import Path

import pytest

from app import wire_contract
from app.handlers import payloads
from app.wire_contract import (
    COMMAND_PAYLOADS,
    FIXTURE_PATH,
    TUPLE_EVENTS,
    build_contract,
    bump_missing,
    diff_contracts,
    dumps,
)

HANDLERS = Path(__file__).parents[1] / "app" / "handlers"


def test_the_tracked_contract_is_the_tree_s():
    """A stale fixture is a wire change nobody wrote down.

    Regenerate with `backend/.venv/bin/python scripts/check-wire-contract.py --write`.
    """
    current = build_contract()
    tracked = json.loads(FIXTURE_PATH.read_text())
    assert diff_contracts(tracked, current) == [], "fixtures/wire_contract.json is stale"
    assert tracked["protocolVersion"] == current["protocolVersion"]
    assert FIXTURE_PATH.read_text() == dumps(current), "regenerate: formatting drifted"


def test_every_registered_command_declares_its_payload():
    registered = set()
    for path in HANDLERS.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "on"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                registered.add(node.args[0].value)
    registered -= wire_contract.BUILTIN_EVENTS
    assert registered == set(COMMAND_PAYLOADS), (
        "COMMAND_PAYLOADS in app/wire_contract.py must name every registered command, and only those"
    )
    # Every model a handler parses is in the table, so a model swap is visible.
    parsed = set()
    for path in HANDLERS.rglob("*.py"):
        parsed.update(re.findall(r"parse_payload\((\w+),", path.read_text(encoding="utf-8")))
    declared = {p.__name__ for p in COMMAND_PAYLOADS.values() if not isinstance(p, str)}
    assert parsed - {"model"} <= declared, f"parsed but undeclared: {sorted(parsed - declared)}"


def test_the_contract_lists_exactly_the_events_the_wire_document_does():
    """§5's table is the human record; extraction must not silently miss one."""
    doc = (wire_contract.REPO_ROOT / "docs" / "wire-protocol.md").read_text(encoding="utf-8")
    section = doc[doc.index("## 5. Server"):doc.index("### Key payload shapes")]
    documented = set()
    for row in re.findall(r"^\| `([^|]+?)` \|", section, re.M):
        documented.update(re.findall(r"[a-z_]+", row))
    assert set(build_contract()["events"]) == documented


def test_tuple_events_are_events_the_server_emits():
    events = build_contract()["events"]
    assert set(TUPLE_EVENTS) <= set(events)
    for name, layout in TUPLE_EVENTS.items():
        assert events[name]["layout"] == layout


# --- the four changes a name check accepts -------------------------------------


@pytest.fixture(scope="module")
def baseline_contract():
    # Diff-policy cases change copies of the same input. Extraction and
    # file-mutation cases below still build fresh contracts explicitly.
    return build_contract()


def _mutated(base, mutate) -> tuple[dict, dict]:
    current = copy.deepcopy(base)
    mutate(current)
    return base, current


def test_a_field_type_change_is_a_contract_change(baseline_contract):
    def mutate(c):
        c["commands"]["join_room"]["payload"]["properties"]["nickname"]["type"] = "integer"

    base, current = _mutated(baseline_contract, mutate)
    assert any("join_room.payload.properties.nickname.type" in line for line in diff_contracts(base, current))
    assert bump_missing(base, current)


def test_a_field_losing_a_bound_is_a_contract_change(baseline_contract):
    def mutate(c):
        del c["commands"]["join_room"]["payload"]["properties"]["nickname"]["maxLength"]

    base, current = _mutated(baseline_contract, mutate)
    assert diff_contracts(base, current)


def test_a_key_moving_between_builders_is_a_contract_change(baseline_contract):
    """The union of keys is unchanged; the owner is not."""

    def mutate(c):
        builders = c["payloadBuilders"]
        source = next(name for name, keys in builders.items() if "playerId" in keys)
        target = next(name for name, keys in builders.items() if "playerId" not in keys)
        builders[source] = [k for k in builders[source] if k != "playerId"]
        builders[target] = sorted(builders[target] + ["playerId"])

    base, current = _mutated(baseline_contract, mutate)
    before = {k for keys in base["payloadBuilders"].values() for k in keys}
    after = {k for keys in current["payloadBuilders"].values() for k in keys}
    assert before == after, "the mutation must keep the name union identical"
    assert diff_contracts(base, current)


def test_a_tuple_reorder_is_a_contract_change(baseline_contract):
    def mutate(c):
        layout = c["events"]["canvas_commit"]["layout"]
        layout[0], layout[1] = layout[1], layout[0]

    base, current = _mutated(baseline_contract, mutate)
    assert any("events.canvas_commit.layout" in line for line in diff_contracts(base, current))


def test_a_binary_layout_change_under_the_same_tag_is_a_contract_change(tmp_path, monkeypatch):
    """The tag stays 1; the fixture's bytes - the layout examples - do not."""
    fixture = Path(wire_contract.REPO_ROOT / "fixtures" / "canvas_protocol_v1.json")
    altered = tmp_path / "fixtures" / "canvas_protocol_v1.json"
    altered.parent.mkdir()
    for name in wire_contract.PINNED_FIXTURES:
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_bytes((wire_contract.REPO_ROOT / name).read_bytes())
    document = json.loads(fixture.read_text())
    document["frames"][0]["wire"] = "ff" + document["frames"][0]["wire"][2:]
    altered.write_text(json.dumps(document))
    base = build_contract()
    monkeypatch.setattr(wire_contract, "REPO_ROOT", tmp_path)
    current = build_contract()
    assert diff_contracts(base, current) == [
        f"~ fixtures.fixtures/canvas_protocol_v1.json: {json.dumps(base['fixtures']['fixtures/canvas_protocol_v1.json'])} -> {json.dumps(current['fixtures']['fixtures/canvas_protocol_v1.json'])}"
    ]


def test_a_new_refusal_code_and_a_new_event_are_contract_changes(baseline_contract):
    def mutate(c):
        c["refusal"]["codes"].append("brand_new")
        c["events"]["brand_new_event"] = {"shape": "object"}

    base, current = _mutated(baseline_contract, mutate)
    assert len(diff_contracts(base, current)) == 2


# --- the two decisions the CI script makes -----------------------------------


def test_a_documented_version_bump_makes_the_change_acceptable(baseline_contract):
    def mutate(c):
        c["commands"]["join_room"]["payload"]["properties"]["nickname"]["type"] = "integer"
        c["protocolVersion"] += 1

    base, current = _mutated(baseline_contract, mutate)
    assert diff_contracts(base, current), "the change is still reported"
    assert not bump_missing(base, current)


def test_regenerating_the_fixture_under_the_same_version_is_still_a_change(baseline_contract):
    """The check compares against the base revision, not the working tree, so
    rewriting the fixture cannot launder a change."""

    def mutate(c):
        c["commands"]["join_room"]["payload"]["properties"]["nickname"]["type"] = "integer"

    base, current = _mutated(baseline_contract, mutate)
    regenerated = json.loads(dumps(current))  # what --write would commit
    assert bump_missing(base, regenerated)
    assert not diff_contracts(current, regenerated), "against the working tree it looks clean"


def test_an_unchanged_contract_needs_no_bump(baseline_contract):
    base = baseline_contract
    assert diff_contracts(base, copy.deepcopy(base)) == []
    assert not bump_missing(base, copy.deepcopy(base))


def test_the_document_says_what_it_cannot_see():
    """Review must cover meaning and privacy; the module says so where a
    reader will look for the guarantee."""
    text = (wire_contract.__doc__ or "")
    assert "meaning" in text and "privacy" in text
    assert payloads.RequestModel.model_config.get("extra") == "forbid", (
        "an unknown key is refused, which is what makes the schema the whole surface"
    )
