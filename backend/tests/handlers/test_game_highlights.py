"""Getting a finished game's highlights to the room that played it."""
from __future__ import annotations

import pytest

from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import build_context, build_room, play_to_completion

pytestmark = pytest.mark.asyncio


def game_ended_payload(ctx) -> dict:
    for call in ctx.sio.emit.await_args_list:
        if call.args[0] == "game_ended":
            return call.args[1]
    raise AssertionError("no game_ended was emitted")


async def test_game_ended_carries_the_highlights():
    """Everyone guesses everything here, so no prompt was the hard one."""
    room_manager, room, players = build_room(rounds=2)
    ctx = build_context(room_manager, FakeGameHistoryRepository())

    await play_to_completion(ctx, room, players)

    highlights = game_ended_payload(ctx)["highlights"]
    assert highlights, "a completed two-round game produced no highlights"
    assert {h["kind"] for h in highlights} == {
        "fastest_guess",
        "best_drawer",
        "quickest_average",
    }


async def test_a_prompt_someone_missed_becomes_the_hardest():
    room_manager, room, players = build_room(
        rounds=2, accounts={"Ann": "u-ann", "Bob": "u-bob", "Cid": "u-cid"}
    )
    ctx = build_context(room_manager, FakeGameHistoryRepository())

    # Cid never guesses, so no turn is ever guessed by everyone eligible.
    await play_to_completion(ctx, room, players, guessers={"Ann", "Bob"})

    highlights = game_ended_payload(ctx)["highlights"]
    hardest = [h for h in highlights if h["kind"] == "hardest_prompt"]
    assert len(hardest) == 1
    assert hardest[0]["correctGuessCount"] < hardest[0]["totalGuesserCount"]


async def test_highlights_do_not_depend_on_the_history_repository():
    """The write is optional and allowed to fail; the final screen is not."""
    room_manager, room, players = build_room(rounds=2)
    ctx = build_context(room_manager, None)
    assert ctx.game_history_repo is None

    await play_to_completion(ctx, room, players)

    assert game_ended_payload(ctx)["highlights"]


async def test_a_failing_history_write_still_leaves_highlights():
    room_manager, room, players = build_room(rounds=2)
    ctx = build_context(room_manager, FakeGameHistoryRepository(fail=True))

    await play_to_completion(ctx, room, players)

    assert game_ended_payload(ctx)["highlights"]


async def test_the_waiting_room_still_reports_the_last_game_highlights():
    """A player who reloads into the waiting room sees what the room saw."""
    room_manager, room, players = build_room(rounds=2)
    ctx = build_context(room_manager, FakeGameHistoryRepository())

    await play_to_completion(ctx, room, players)

    assert room.state == "waiting"
    assert room.to_state_payload()["lastGameHighlights"] == room.last_game_highlights
    assert room.last_game_highlights


async def test_a_new_game_clears_the_previous_highlights():
    room_manager, room, players = build_room(rounds=2)
    ctx = build_context(room_manager, FakeGameHistoryRepository())

    await play_to_completion(ctx, room, players)
    assert room.last_game_highlights

    await ctx.game_flow._start_fresh_game(room, list(room.player_list()))

    assert room.last_game_highlights == []
    # And a room mid-game does not report stale highlights to a late joiner.
    assert room.to_state_payload()["lastGameHighlights"] == []
