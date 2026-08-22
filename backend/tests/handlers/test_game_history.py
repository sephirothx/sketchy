"""Persisting a finished game: what is recorded, and what deliberately is not."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import socketio

from app.game import MAX_GUESS_POINTS, MIN_GUESS_POINTS, Game
from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager
from app.prompts import PROMPTS
from app.services import game_flow
from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import (
    build_context,
    build_room,
    play_to_completion,
)

pytestmark = pytest.mark.asyncio


def attach_curated_sources(room, *revision_ids: str) -> None:
    """Give the real Game source IDs while its prompt text uses the built-ins."""
    room.prompt_list_revision_ids = list(revision_ids or ("revision-standard",))
    room.prompt_version_ids = {
        prompt: f"version-{index}" for index, prompt in enumerate(PROMPTS)
    }


async def test_completed_game_records_every_round_with_participants_and_guesses():
    room_manager, room, players = build_room(rounds=2)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    assert len(history.saved) == 1
    saved = history.saved[0]
    # Two players, two rounds each taking a turn: four turns, all recorded.
    assert len(saved.turns) == 4
    assert [r.turn_number for r in saved.turns] == [1, 2, 3, 4]
    assert all(r.prompt for r in saved.turns)
    assert {p.user_id for p in saved.participants} == {"user-ann", "user-bob"}
    assert saved.record.player_count == 2
    assert saved.record.room_name == "Studio"
    assert saved.record.total_rounds == 2
    assert saved.record.finished_at >= saved.record.started_at
    # Every turn has exactly one eligible guesser, and they all guessed.
    assert len(saved.guesses) == 4
    assert {g.turn_id for g in saved.guesses} == {turn.id for turn in saved.turns}


async def test_seat_without_an_account_is_skipped_and_the_rest_still_persists():
    room_manager, room, players = build_room(
        rounds=1,
        accounts={"Ann": "user-ann", "Bob": "user-bob", "Cid": None},
    )
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    saved = history.saved[0]
    assert {p.user_id for p in saved.participants} == {"user-ann", "user-bob"}
    assert saved.record.player_count == 2
    # Three turns were played but Cid's cannot be hung off a drawer account.
    assert len(saved.turns) == 2
    assert all(r.drawer_user_id in {"user-ann", "user-bob"} for r in saved.turns)
    assert all(g.user_id in {"user-ann", "user-bob"} for g in saved.guesses)


async def test_departed_player_still_counts_as_a_participant():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_prompt_choice()
    game.set_phase_deadline(game.drawing_seconds)
    await flow._end_turn(room)
    ctx.timers.cancel_phase_timer(room.id)
    await flow._finish_or_next(room)

    # The first drawer quits before the closing turn is played out.
    leaver = players["Ann"]
    room_manager.remove_player(room, leaver.id)
    await flow._remove_player_from_game(room, leaver.id)
    while room.game is not None:
        game = room.game
        game.force_prompt_choice()
        game.set_phase_deadline(game.drawing_seconds)
        await flow._end_turn(room)
        ctx.timers.cancel_phase_timer(room.id)
        await flow._finish_or_next(room)
    await ctx.timers.close()

    assert len(history.saved) == 1
    saved = history.saved[0]
    assert {p.user_id for p in saved.participants} == {"user-ann", "user-bob"}
    assert any(r.drawer_user_id == "user-ann" for r in saved.turns)


async def test_restart_discards_the_turns_played_so_far():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_prompt_choice()
    game.set_phase_deadline(game.drawing_seconds)
    await flow._end_turn(room)
    ctx.timers.cancel_phase_timer(room.id)

    await flow._start_fresh_game(room, room.player_list(), restarted=True)
    assert room.game.completed_turns == []

    await play_to_completion(ctx, room, players)

    assert len(history.saved) == 1
    # Only the restarted game's turns, never the abandoned one's.
    assert len(history.saved[0].turns) == 2


async def test_abandoned_game_is_never_persisted():
    room_manager, room, players = build_room(rounds=2)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_prompt_choice()
    game.set_phase_deadline(game.drawing_seconds)
    await flow._end_turn(room)
    ctx.timers.cancel_phase_timer(room.id)

    for player in list(room.player_list()):
        room_manager.remove_player(room, player.id)
        await flow._remove_player_from_game(room, player.id)
    await ctx.timers.close()

    assert room.game is None
    assert history.saved == []


async def test_a_game_with_only_one_account_is_not_recorded():
    """One recordable seat would be ranked first against nobody."""
    room_manager, room, players = build_room(
        rounds=1, accounts={"Ann": "user-ann", "Bob": None}
    )
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    assert history.saved == []


async def test_an_opponent_leaving_does_not_erase_the_turns_played():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_prompt_choice()
    game.set_phase_deadline(game.drawing_seconds)
    await flow._end_turn(room)
    ctx.timers.cancel_phase_timer(room.id)

    # One seat left: `total_turns` collapses and the game reports finished.
    leaver = players["Bob"]
    room_manager.remove_player(room, leaver.id)
    await flow._remove_player_from_game(room, leaver.id)
    if room.game is not None:
        await flow._finish_or_next(room)
    await ctx.timers.close()

    assert len(history.saved) == 1
    saved = history.saved[0]
    assert {p.user_id for p in saved.participants} == {"user-ann", "user-bob"}
    assert len(saved.turns) == 1


async def test_a_real_game_carries_its_analytics_through_to_the_write():
    """The numbers survive the whole path: turn -> builder -> repository."""
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.hint_mode = "purchase"
    game.force_prompt_choice()
    game.set_phase_deadline(game.drawing_seconds)
    guesser = next(p for p in room.player_list() if p.id != game.current_drawer)

    price = game.hint_cost(guesser.id)
    assert game.buy_hint_letter(guesser.id, 0) is True
    game.submit_guess(guesser.id, "definitely-not-the-prompt")
    gross = game.remaining_seconds() / game.drawing_seconds
    gross = round(MIN_GUESS_POINTS + (MAX_GUESS_POINTS - MIN_GUESS_POINTS) * gross)
    _, awarded = game.submit_guess(guesser.id, game.prompt)

    await flow._end_turn(room)
    ctx.timers.cancel_phase_timer(room.id)
    await flow._finish_or_next(room)
    while room.game is not None:
        game = room.game
        game.force_prompt_choice()
        game.set_phase_deadline(game.drawing_seconds)
        await flow._end_turn(room)
        ctx.timers.cancel_phase_timer(room.id)
        await flow._finish_or_next(room)
    await ctx.timers.close()

    saved = history.saved[0]
    first_round = saved.turns[0]
    assert first_round.guesser_count == 1
    assert first_round.prompt_auto_picked is True
    assert first_round.end_reason == "all_guessed"
    assert first_round.wrong_guess_count == 1

    hinted = next(g for g in saved.guesses if g.turn_id == first_round.id)
    assert hinted.hints_used == 1
    assert hinted.points_spent_on_hints == price
    # What lands in history is what the player actually banked: net of hints.
    assert hinted.points_awarded == awarded == gross - price
    assert hinted.wrong_guesses_before == 1

    # Both players were in the rotation for both turns.
    assert {p.turns_played for p in saved.participants} == {2}


async def test_the_result_is_snapshotted_before_the_room_reopens():
    """A game starting in the gaps must not rewrite the finished game.

    `_finish_or_next` marks the room waiting and then awaits, so a `start_game`
    landing in one of those gaps resets every score and clears the departed
    seats. The recorded game has to be the one that was actually played.
    """
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    class RestartingWordRepo:
        """Stands in for the prompt-stat writes, and restarts the room mid-way.

        These run only once the game is finished, which is exactly the window
        where the room is already reporting itself as waiting.
        """

        def __init__(self) -> None:
            self.restarted = False

        async def record_prompt_usage(self, slugs, usage):
            if not self.restarted:
                self.restarted = True
                await flow._start_fresh_game(room, room.player_list())

    ctx.prompt_list_repo = RestartingWordRepo()
    room.prompt_list_slugs = ["english_standard"]
    attach_curated_sources(room)

    await flow._start_fresh_game(room, room.player_list())
    # Two players over one round is two turns; the interference lands on the
    # second, which is the one that finishes the game.
    expected_scores: dict[str, int] = {}
    for _ in range(2):
        game = room.game
        game.force_prompt_choice()
        game.set_phase_deadline(game.drawing_seconds)
        guesser = next(p for p in room.player_list() if p.id != game.current_drawer)
        game.submit_guess(guesser.id, game.prompt)
        await flow._end_turn(room)
        ctx.timers.cancel_phase_timer(room.id)
        expected_scores = {p.user_id: p.score for p in room.player_list()}
        await flow._finish_or_next(room)
    ctx.timers.cancel_phase_timer(room.id)
    await ctx.timers.close()

    assert ctx.prompt_list_repo.restarted, "the interleaving under test never happened"
    assert len(history.saved) == 1
    saved = history.saved[0]
    assert len(saved.turns) == 2
    # The scores the game finished with, not the ones the restart reset to.
    assert {p.user_id: p.final_score for p in saved.participants} == expected_scores
    assert all(score > 0 for score in expected_scores.values())


async def test_the_game_ends_for_players_before_the_write_is_attempted():
    """A database round trip must not sit between a player and the result."""
    room_manager, room, players = build_room(rounds=1)
    order: list[str] = []

    class SlowRepo(FakeGameHistoryRepository):
        async def save_game(self, *args):
            order.append("saved")
            return await super().save_game(*args)

    history = SlowRepo()
    ctx = build_context(room_manager, history)
    original_emit = ctx.sio.emit

    async def tracking_emit(event, *args, **kwargs):
        if event == "game_ended":
            order.append("game_ended")
        return await original_emit(event, *args, **kwargs)

    ctx.sio.emit = tracking_emit

    await play_to_completion(ctx, room, players)

    assert order == ["game_ended", "saved"]


async def test_a_failing_write_does_not_break_the_end_of_the_game():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository(fail=True)
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    assert room.state == "waiting"
    emitted = [call.args[0] for call in ctx.sio.emit.await_args_list]
    assert "game_ended" in emitted


async def test_history_is_skipped_entirely_without_a_repository():
    room_manager, room, players = build_room(rounds=1)
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(return_value=None)
    sio.save_session = AsyncMock()

    await play_to_completion(ctx, room, players)

    assert room.state == "waiting"


class FakeWordListRepository:
    """Records the batched write, and can stand in for a locked database."""

    def __init__(self, *, timeline=None, hang=False):
        self.calls: list[tuple] = []
        self._timeline = timeline if timeline is not None else []
        self._hang = hang

    async def record_prompt_usage(self, prompt_list_revision_ids, usage):
        if self._hang:
            await asyncio.sleep(3600)
        self.calls.append((tuple(prompt_list_revision_ids), usage))
        self._timeline.append(("prompt", tuple(prompt_list_revision_ids)))


def emitted_payload(ctx, event: str):
    for call in ctx.sio.emit.await_args_list:
        if call.args[0] == event:
            return call.args[1]
    return None


async def test_game_ended_is_emitted_before_any_word_usage_is_written():
    """Nothing a player is waiting to see may sit behind the metric writes."""
    timeline: list[tuple] = []
    room_manager, room, players = build_room(rounds=1)
    room.prompt_list_slugs = ["english_standard", "english_extended"]
    attach_curated_sources(room, "revision-standard", "revision-extended")
    words = FakeWordListRepository(timeline=timeline)
    ctx = build_context(
        room_manager, FakeGameHistoryRepository(), words, timeline=timeline
    )

    await play_to_completion(ctx, room, players)

    assert ("emit", "game_ended") in timeline
    assert words.calls, "the metrics still have to be recorded"
    first_write = next(i for i, entry in enumerate(timeline) if entry[0] == "prompt")
    assert timeline.index(("emit", "game_ended")) < first_write
    assert timeline.index(("emit", "room_state")) < first_write


async def test_a_hung_word_list_database_cannot_hold_the_end_of_a_game_open():
    """A locked database must cost the counters, not the room."""
    room_manager, room, players = build_room(rounds=1)
    room.prompt_list_slugs = ["english_standard"]
    attach_curated_sources(room)
    words = FakeWordListRepository(hang=True)
    ctx = build_context(room_manager, FakeGameHistoryRepository(), words)

    with patch.object(game_flow, "PROMPT_USAGE_WRITE_TIMEOUT_SECONDS", 0.05):
        await play_to_completion(ctx, room, players)

    assert words.calls == [], "the hung writes never landed"
    # The room was still told the game ended, with the real standings rather
    # than the blank list a racing `start_game` would have left behind.
    payload = emitted_payload(ctx, "game_ended")
    assert payload is not None
    assert [entry["nickname"] for entry in payload["scores"]]
    assert room.state == "waiting"
    assert room.game is None


async def test_every_turn_and_list_is_folded_into_a_single_write():
    """The whole game goes down in one call, not one per turn per list."""
    room_manager, room, players = build_room(rounds=2)
    room.prompt_list_slugs = ["english_standard", "english_extended"]
    attach_curated_sources(room, "revision-standard", "revision-extended")
    words = FakeWordListRepository()
    ctx = build_context(room_manager, FakeGameHistoryRepository(), words)

    await play_to_completion(ctx, room, players)

    # Two players over two rounds is four turns, each offering three words and
    # drawing one - and previously two writes per turn per list, so sixteen.
    assert len(words.calls) == 1
    revision_ids, usage = words.calls[0]
    assert revision_ids == ("revision-standard", "revision-extended")
    assert sum(usage.offers.values()) == 12
    assert sum(totals.picks for totals in usage.picks.values()) == 4
    assert all(prompt.startswith("version-") for prompt in usage.offers)


async def test_custom_only_game_never_writes_curated_usage_on_text_collision():
    room_manager, room, players = build_room(rounds=1)
    room.custom_prompts = ["apple", "kite", "tree"]
    room.custom_prompts_only = True
    room.prompt_list_slugs = ["english_standard"]
    attach_curated_sources(room)
    words = FakeWordListRepository()
    ctx = build_context(room_manager, FakeGameHistoryRepository(), words)

    await play_to_completion(ctx, room, players)

    assert words.calls == []


async def test_mixed_game_attributes_the_source_not_equal_custom_text():
    room_manager, room, players = build_room(rounds=1)
    room.custom_prompts = ["apple"]
    room.curated_prompts = ["apple", "banana", "castle"]
    room.prompt_list_slugs = ["english_standard"]
    attach_curated_sources(room)
    custom_collision_id = room.prompt_version_ids["apple"]
    words = FakeWordListRepository()
    ctx = build_context(room_manager, FakeGameHistoryRepository(), words)

    await play_to_completion(ctx, room, players)

    assert len(words.calls) == 1
    _, usage = words.calls[0]
    assert custom_collision_id not in usage.offers
    assert custom_collision_id not in usage.picks
    assert sum(usage.offers.values()) == 4  # two curated offers over two turns
