"""How a starting game gets its prompts, now that the room does not hold them.

A room used to keep its whole resolved pool resident so that turns could be
served from memory. A game now draws only what it can possibly play - at most
`rounds x max_players x 3` prompts - once, at start. These are the properties
that had to survive the move: the same mixture of curated and quick prompts,
the same shadowing, the same refusal when the lists cannot be read, and content
pinned to the revisions the room was authorized on.
"""
from __future__ import annotations

import asyncio
import random
import time
from unittest.mock import AsyncMock, patch

import pytest
import socketio

from app.flow_timing import timing
from app.handlers import register_all_handlers as register_handlers
from app.handlers import restart
from app.prompts import PROMPTS, letter_histogram
from app.rooms import RestartVote
from app.repositories.interfaces import PromptSample
from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import StubPromptListRepo, build_context, build_room

from app.services import game_flow
from app.services.game_flow import RoomPromptResolutionError

pytestmark = pytest.mark.asyncio


def pin(room, repo, *, revision_ids=("revision-1",)):
    """Put the room in the state `authorize_selection` would have left it in."""
    room.prompt_list_slugs = ["curated"]
    room.prompt_list_revision_ids = list(revision_ids)
    room.prompt_pool_size = len(repo.prompts)
    counts, total = letter_histogram(repo.prompts)
    room.prompt_letter_counts = counts
    room.prompt_letter_total = total
    repo.revision_ids = tuple(revision_ids)


async def test_a_game_draws_only_the_prompts_it_could_ever_play():
    """The ceiling, not the pool: this is the whole point of the change."""
    room_manager, room, _ = build_room(rounds=2)
    room.max_players = 4
    repo = StubPromptListRepo([f"prompt{index}" for index in range(500)])
    pin(room, repo)
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    await ctx.game_flow._start_fresh_game(room, room.player_list())

    assert room.game is not None
    assert len(room.game.prompt_pool) == 2 * 4 * 3
    assert len(room.game.prompt_pool) < len(repo.prompts)


async def test_quick_prompts_keep_the_share_they_had_in_the_merged_pool():
    """Five quick prompts among five hundred are five in five hundred and five.

    Drawing the two halves separately would make a handful of quick prompts as
    likely as the entire curated list, which is not the mixture the host chose.
    """
    # Seeded: the assertion is about the weighting, not about whether an
    # unseeded draw happened to land inside a tolerance. Five prompts in five
    # hundred and five is rare enough that a fair implementation trips a
    # three-times-either-way bound roughly one run in two thousand.
    random.seed(20260828)
    curated = [f"prompt{index}" for index in range(500)]
    custom = [f"mine{index}" for index in range(5)]
    drawn_custom = 0
    trials = 60

    for _ in range(trials):
        room_manager, room, _ = build_room(rounds=2)
        room.max_players = 4
        room.custom_prompts = list(custom)
        repo = StubPromptListRepo(curated)
        pin(room, repo)
        ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

        await ctx.game_flow._start_fresh_game(room, room.player_list())
        drawn_custom += sum(
            1 for prompt in room.game.prompt_pool if prompt in set(custom)
        )

    drawn_total = trials * 2 * 4 * 3
    share = drawn_custom / drawn_total
    expected = len(custom) / (len(custom) + len(curated))
    # Sampling noise is wide at this rate; an even split would be ~50%, and a
    # curated-only draw 0%, so this separates the outcomes that matter.
    assert expected / 3 < share < expected * 3


async def test_a_quick_prompt_shadows_the_curated_answer_of_the_same_name():
    room_manager, room, _ = build_room(rounds=1)
    room.max_players = 2
    room.custom_prompts = ["apple"]
    repo = StubPromptListRepo(["apple", "banana", "castle"])
    pin(room, repo)
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    await ctx.game_flow._start_fresh_game(room, room.player_list())
    game = room.game

    # The room's own "apple" is in play; the curated one is not, and none of
    # its provenance may reach a turn.
    assert "apple" in game.prompt_pool
    assert game.prompt_version_ids.get("apple") is None
    assert game.prompt_source_kind("apple") == "custom"


async def test_a_custom_only_room_never_asks_the_prompt_store():
    room_manager, room, _ = build_room(rounds=1)
    room.max_players = 2
    room.custom_prompts = ["hedgehog", "lighthouse"]
    room.custom_prompts_only = True
    repo = StubPromptListRepo(["apple", "banana"])
    pin(room, repo)
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    await ctx.game_flow._start_fresh_game(room, room.player_list())

    assert repo.draws == 0
    assert set(room.game.prompt_pool) == {"hedgehog", "lighthouse"}
    assert room.game.prompt_source_mode() == "custom"


async def test_a_room_with_neither_lists_nor_quick_prompts_plays_the_built_ins():
    room_manager, room, _ = build_room(rounds=1)
    repo = StubPromptListRepo([])
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    await ctx.game_flow._start_fresh_game(room, room.player_list())

    assert repo.draws == 0
    assert room.game.prompt_pool is None
    assert room.game.prompt_source_mode() == "builtin_fallback"
    # The built-in list is what a turn is served from.
    assert set(room.game.start_next_turn(canvas_generation=1)) <= set(PROMPTS)


async def test_a_draw_that_cannot_be_made_refuses_the_start():
    """R-LIST-06a: never open quietly on the built-in list instead."""
    room_manager, room, _ = build_room(rounds=1)
    repo = StubPromptListRepo(["apple", "banana"])
    pin(room, repo)
    repo.sample_prompts = AsyncMock(side_effect=RuntimeError("store is down"))
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    with pytest.raises(RoomPromptResolutionError):
        await ctx.game_flow._start_fresh_game(room, room.player_list())


async def test_a_refused_start_leaves_the_room_exactly_as_it_was():
    """A start that cannot draw must not half-begin.

    Starting a game clears the previous one - scores, recap, departed seats -
    and marks the room as playing. If the draw fails after that, the room is
    left claiming to play a game that does not exist, and every later start is
    refused as one already in progress while nothing is running.
    """
    room_manager, room, players = build_room(rounds=1)
    repo = StubPromptListRepo(["apple", "banana"])
    pin(room, repo)
    repo.sample_prompts = AsyncMock(side_effect=RuntimeError("store is down"))
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    room.last_game_scores = [{"nickname": "Ann", "score": 10}]
    for index, player in enumerate(players.values()):
        player.score = 10 * (index + 1)
    scores_before = {player.id: player.score for player in players.values()}

    with pytest.raises(RoomPromptResolutionError):
        await ctx.game_flow._start_fresh_game(room, room.player_list())

    assert room.state == "waiting"
    assert room.game is None
    assert room.last_game_scores == [{"nickname": "Ann", "score": 10}]
    assert {
        player.id: player.score for player in players.values()
    } == scores_before


async def test_wheel_prices_come_from_the_whole_pool_not_the_sample():
    """A 24-prompt sample would price rare letters off a handful of words.

    The pinned distribution is what the room actually draws from, so the price
    a player is quoted does not swing on the luck of one draw.
    """
    curated = [f"prompt{index}" for index in range(500)]
    room_manager, room, _ = build_room(rounds=2)
    room.max_players = 4
    room.custom_prompts = ["zzzz"]
    repo = StubPromptListRepo(curated)
    pin(room, repo)
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    await ctx.game_flow._start_fresh_game(room, room.player_list())
    game = room.game

    curated_counts, curated_total = letter_histogram(curated)
    custom_counts, custom_total = letter_histogram(["zzzz"])
    assert game.letter_total == curated_total + custom_total
    assert game.letter_counts["z"] == curated_counts.get(
        "z", 0
    ) + custom_counts["z"]
    # And it is that distribution the price reads, not the drawn sample.
    frequencies = game._letter_frequencies()
    assert frequencies["z"] == pytest.approx(
        game.letter_counts["z"] / game.letter_total
    )


async def test_a_game_keeps_the_revision_it_started_on():
    """R-LIST-07: a list edited mid-game must not reach a turn in flight."""
    room_manager, room, _ = build_room(rounds=2)
    room.max_players = 2
    repo = StubPromptListRepo(["apple", "banana", "castle", "dragon"])
    pin(room, repo)
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    await ctx.game_flow._start_fresh_game(room, room.player_list())
    started_with = set(room.game.prompt_pool)

    # The list is rewritten underneath the running game.
    repo.prompts = ["entirely", "different", "content"]

    offered: set[str] = set()
    for turn in range(3):
        offered |= set(
            room.game.start_next_turn(canvas_generation=turn + 2)
        )

    assert offered <= started_with
    assert not offered & {"entirely", "different", "content"}


async def test_a_draw_that_never_answers_is_given_up_on():
    """An unbounded database call on a start path would hang the host.

    The refusal is the same one an outright failure gets: the point is that a
    store which accepts the query and never answers cannot hold the room.
    """
    room_manager, room, _ = build_room(rounds=1)
    repo = StubPromptListRepo(["apple", "banana"])
    pin(room, repo)

    async def never_answers(*_args, **_kwargs):
        await asyncio.sleep(3600)

    repo.sample_prompts = never_answers
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    with patch.object(game_flow, "PROMPT_DRAW_TIMEOUT_SECONDS", 0.01):
        with pytest.raises(RoomPromptResolutionError):
            await ctx.game_flow._start_fresh_game(room, room.player_list())

    assert room.game is None
    assert room.state == "waiting"


async def test_shadowing_quick_prompts_keep_the_share_the_merged_pool_gave_them():
    """Shadowed curated answers are not drawable, so they cannot dilute the mix.

    The pool this replaces dropped a curated answer a quick prompt had already
    claimed, *then* sampled. Weighting against the raw list size instead counts
    prompts that can never be drawn, and hands the room's own prompts a much
    smaller share of the game than the host arranged.
    """
    random.seed(20260828)
    curated = [f"prompt{index}" for index in range(500)]
    # Every one of these shadows a curated answer of the same name, so the
    # merged pool is 400 quick prompts and the 100 curated ones left over.
    custom = curated[:400]
    drawn_custom = 0
    trials = 30

    for _ in range(trials):
        room_manager, room, _ = build_room(rounds=2)
        room.max_players = 4
        room.custom_prompts = list(custom)
        repo = StubPromptListRepo(curated)
        pin(room, repo)
        ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

        await ctx.game_flow._start_fresh_game(room, room.player_list())
        # Shadowing means a shared answer in the pool is the room's own.
        drawn_custom += sum(
            1 for prompt in room.game.prompt_pool if prompt in set(custom)
        )

    share = drawn_custom / (trials * 2 * 4 * 3)
    expected = len(custom) / (len(custom) + len(curated) - len(custom))
    assert expected * 0.8 < share < min(1.0, expected * 1.2)


async def test_a_custom_only_room_prices_the_wheel_from_its_own_prompts():
    """Selecting lists and then playing only quick prompts must not price them.

    `customPromptsOnly` leaves the picked lists pinned - the host can turn it
    back off - but nothing in those lists can be drawn, so charging list-wide
    letter frequencies bills players for content the game will never show.
    """
    room_manager, room, _ = build_room(rounds=1)
    room.max_players = 2
    room.custom_prompts = ["zzzz", "qqqq"]
    room.custom_prompts_only = True
    repo = StubPromptListRepo([f"prompt{index}" for index in range(500)])
    pin(room, repo)
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    await ctx.game_flow._start_fresh_game(room, room.player_list())
    game = room.game

    expected_counts, expected_total = letter_histogram(["zzzz", "qqqq"])
    assert game.letter_total == expected_total
    assert dict(game.letter_counts) == expected_counts
    # "p", all over the pinned lists and in nothing being played, is worthless.
    assert game._letter_frequencies()["p"] == 0.0


async def test_start_game_tells_the_host_when_the_draw_fails():
    """The refusal has to reach the host, not escape the socket handler.

    `refresh_room_prompt_selection` already answers this way when a list cannot
    be read. Drawing the prompts is a second read on the same path and fails
    for the same reasons, so it must be answered the same way.
    """
    room_manager, room, players = build_room(rounds=1)
    host = players["Ann"]
    host.is_host = True
    repo = StubPromptListRepo(["apple", "banana"])
    pin(room, repo)
    repo.sample_prompts = AsyncMock(side_effect=RuntimeError("store is down"))

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager, prompt_list_repo=repo)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": host.id}
    )

    result = await sio.handlers["/"]["start_game"](host.sid, None)

    assert result == {
        "ok": False,
        "error": "Prompt lists could not be loaded. Please try again.",
        "field": "promptListSlugs",
    }
    # And the room is still startable once the store comes back.
    assert room.state == "waiting"
    assert room.game is None


async def test_a_restart_whose_draw_fails_is_cancelled_rather_than_crashing():
    """The restart runs in a timer task, where an exception is simply lost.

    Players would sit watching a game that was already torn down, with no
    restart arriving and nothing said about why.
    """
    room_manager, room, players = build_room(rounds=1)
    repo = StubPromptListRepo(["apple", "banana"])
    pin(room, repo)
    repo.sample_prompts = AsyncMock(side_effect=RuntimeError("store is down"))
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)
    room.state = "playing"

    seats = list(players.values())
    vote = RestartVote(
        proposer_id=seats[0].id,
        proposer_nickname=seats[0].nickname,
        eligible_voter_ids=tuple(player.id for player in seats),
        votes={player.id: True for player in seats},
        expires_at=time.time() + 60,
        status="approved",
    )
    room.restart_vote = vote

    with patch.object(timing, "restart_delay_seconds", 0.01):
        restart._schedule_restart(ctx, room, vote)
        await asyncio.sleep(0.1)

    assert room.state == "waiting"
    assert room.game is None
    assert room.restart_vote is None
    announced = " ".join(
        str(call.args) for call in ctx.sio.emit.await_args_list
    )
    assert "restart was cancelled" in announced


async def test_a_list_room_whose_content_vanished_is_refused_not_quietly_rebuilt():
    """R-LIST-06a and R-LIST-08: an empty list fails visibly.

    Authorization proves the lists hold prompts, but moderation can take the
    last of them away between then and the draw. Falling through to the
    built-in list would open the room on content the host never chose, which
    is the exact substitution those rules exist to prevent.
    """
    room_manager, room, _ = build_room(rounds=1)
    repo = StubPromptListRepo(["apple", "banana"])
    pin(room, repo)
    # Authorized on two prompts; both hidden by the time the draw lands.
    repo.prompts = []
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    with pytest.raises(RoomPromptResolutionError):
        await ctx.game_flow._start_fresh_game(room, room.player_list())

    assert room.state == "waiting"
    assert room.game is None


async def test_the_roster_is_read_after_the_draw_not_before_it():
    """Seating is not held by `room.lock`, and the draw is a database call.

    A player who joins while it is in flight is seated, but finds no game to
    enrol in; building the rotation from the roster captured beforehand would
    seat them for a game they can never take a turn in.
    """
    room_manager, room, players = build_room(rounds=1)
    repo = StubPromptListRepo(["apple", "banana", "castle"])
    pin(room, repo)
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    stale_roster = room.player_list()
    latecomer = {}

    original = repo.sample_prompts

    async def join_midway(*args, **kwargs):
        latecomer["player"] = room_manager.add_player(room, "Cass")
        return await original(*args, **kwargs)

    repo.sample_prompts = join_midway

    await ctx.game_flow._start_fresh_game(room, stale_roster)

    assert latecomer["player"].id in room.game.turn_order
    assert len(room.game.turn_order) == len(players) + 1


async def test_a_takedown_between_counting_and_drawing_still_refuses():
    """The count and the draw are two statements, and Postgres reads each fresh.

    A takedown committing between them leaves a count saying there is content
    and a draw returning none. Trusting the count would hand `Game` an empty
    pool, which it reads as the built-in list - the same forbidden fallback,
    reached by a narrower door.
    """
    room_manager, room, _ = build_room(rounds=1)
    repo = StubPromptListRepo(["apple", "banana"])
    pin(room, repo)

    async def counted_but_gone(*_args, **_kwargs):
        return PromptSample(prompts=(), drawable=2)

    repo.sample_prompts = counted_but_gone
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    with pytest.raises(RoomPromptResolutionError):
        await ctx.game_flow._start_fresh_game(room, room.player_list())

    assert room.state == "waiting"
    assert room.game is None


async def test_a_short_draw_is_believed_over_the_count():
    """Fewer rows than asked for means fewer exist, whatever the count said."""
    room_manager, room, _ = build_room(rounds=1)
    room.max_players = 2
    room.custom_prompts = ["mine"]
    repo = StubPromptListRepo(["apple", "banana", "castle"])
    pin(room, repo)

    async def one_row_only(*_args, **_kwargs):
        drawn = await StubPromptListRepo.sample_prompts(
            repo, list(room.prompt_list_revision_ids), limit=1
        )
        return PromptSample(prompts=drawn.prompts, drawable=500)

    repo.sample_prompts = one_row_only
    ctx = build_context(room_manager, FakeGameHistoryRepository(), repo)

    await ctx.game_flow._start_fresh_game(room, room.player_list())

    # Whatever the count claimed, the game may only hold what came back.
    curated = [p for p in room.game.prompt_pool if p != "mine"]
    assert len(curated) <= 1
    assert room.game.prompt_pool
