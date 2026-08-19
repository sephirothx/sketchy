"""Persisting a finished game: what is recorded, and what deliberately is not."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
import socketio

from app.game import Game, Phase
from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager, STARTING_SCORE
from tests.fake_game_history_repo import FakeGameHistoryRepository

pytestmark = pytest.mark.asyncio


def build_room(*, rounds: int = 1, accounts: dict[str, str | None] | None = None):
    """A room of seats keyed by nickname, each bound to an account (or none)."""
    accounts = accounts or {"Ann": "user-ann", "Bob": "user-bob"}
    room_manager = RoomManager()
    room = room_manager.create_room(name="Studio", is_public=True, rounds=rounds)
    players = {}
    for nickname, user_id in accounts.items():
        player = room_manager.add_player(room, nickname, user_id=user_id)
        player.sid = f"sid-{nickname.lower()}"
        players[nickname] = player
    return room_manager, room, players


def build_context(room_manager, history_repo):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, game_history_repo=history_repo)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(return_value=None)
    sio.save_session = AsyncMock()
    return ctx


async def play_to_completion(ctx, room, players, *, guessers=None):
    """Drive real turns through the flow service until the game reports finished.

    Uses the same entry points the timers do, so the recorded history is
    produced by the code path a real game takes rather than by hand-built state.
    """
    flow = ctx.game_flow
    await flow._start_fresh_game(room, [p for p in room.player_list()])
    while room.game is not None:
        game = room.game
        game.force_word_choice()
        game.set_phase_deadline(game.drawing_seconds)
        for player in room.player_list():
            if player.id == game.current_drawer:
                continue
            if guessers is not None and player.nickname not in guessers:
                continue
            game.submit_guess(player.id, game.word)
        await flow._end_round(room)
        ctx.timers.cancel_phase_timer(room.id)
        await flow._finish_or_next(room)
    await ctx.timers.close()


async def test_completed_game_records_every_round_with_participants_and_guesses():
    room_manager, room, players = build_room(rounds=2)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    assert len(history.saved) == 1
    saved = history.saved[0]
    # Two players, two rounds each taking a turn: four turns, all recorded.
    assert len(saved.rounds) == 4
    assert [r.turn_number for r in saved.rounds] == [1, 2, 3, 4]
    assert all(r.word for r in saved.rounds)
    assert {p.user_id for p in saved.participants} == {"user-ann", "user-bob"}
    assert saved.record.player_count == 2
    assert saved.record.room_name == "Studio"
    assert saved.record.total_rounds == 2
    assert saved.record.finished_at >= saved.record.started_at
    # Every turn has exactly one eligible guesser, and they all guessed.
    assert len(saved.guesses) == 4
    assert {g.round_index for g in saved.guesses} == {0, 1, 2, 3}


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
    assert len(saved.rounds) == 2
    assert all(r.drawer_user_id in {"user-ann", "user-bob"} for r in saved.rounds)
    assert all(g.user_id in {"user-ann", "user-bob"} for g in saved.guesses)


async def test_departed_player_still_counts_as_a_participant():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_word_choice()
    game.set_phase_deadline(game.drawing_seconds)
    await flow._end_round(room)
    ctx.timers.cancel_phase_timer(room.id)
    await flow._finish_or_next(room)

    # The first drawer quits before the closing turn is played out.
    leaver = players["Ann"]
    room_manager.remove_player(room, leaver.id)
    await flow._remove_player_from_game(room, leaver.id)
    while room.game is not None:
        game = room.game
        game.force_word_choice()
        game.set_phase_deadline(game.drawing_seconds)
        await flow._end_round(room)
        ctx.timers.cancel_phase_timer(room.id)
        await flow._finish_or_next(room)
    await ctx.timers.close()

    assert len(history.saved) == 1
    saved = history.saved[0]
    assert {p.user_id for p in saved.participants} == {"user-ann", "user-bob"}
    assert any(r.drawer_user_id == "user-ann" for r in saved.rounds)


async def test_restart_discards_the_rounds_played_so_far():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_word_choice()
    game.set_phase_deadline(game.drawing_seconds)
    await flow._end_round(room)
    ctx.timers.cancel_phase_timer(room.id)

    await flow._start_fresh_game(room, room.player_list(), restarted=True)
    assert room.game.completed_turns == []

    await play_to_completion(ctx, room, players)

    assert len(history.saved) == 1
    # Only the restarted game's turns, never the abandoned one's.
    assert len(history.saved[0].rounds) == 2


async def test_abandoned_game_is_never_persisted():
    room_manager, room, players = build_room(rounds=2)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_word_choice()
    game.set_phase_deadline(game.drawing_seconds)
    await flow._end_round(room)
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


async def test_an_opponent_leaving_does_not_erase_the_rounds_played():
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.force_word_choice()
    game.set_phase_deadline(game.drawing_seconds)
    await flow._end_round(room)
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
    assert len(saved.rounds) == 1


async def test_a_real_game_carries_its_analytics_through_to_the_write():
    """The numbers survive the whole path: turn -> builder -> repository."""
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.hint_mode = "purchase"
    game.force_word_choice()
    game.set_phase_deadline(game.drawing_seconds)
    guesser = next(p for p in room.player_list() if p.id != game.current_drawer)

    price = game.hint_cost(guesser.id)
    assert game.buy_hint_letter(guesser.id, 0) is True
    game.submit_guess(guesser.id, "definitely-not-the-word")
    game.submit_guess(guesser.id, game.word)

    await flow._end_round(room)
    ctx.timers.cancel_phase_timer(room.id)
    await flow._finish_or_next(room)
    while room.game is not None:
        game = room.game
        game.force_word_choice()
        game.set_phase_deadline(game.drawing_seconds)
        await flow._end_round(room)
        ctx.timers.cancel_phase_timer(room.id)
        await flow._finish_or_next(room)
    await ctx.timers.close()

    saved = history.saved[0]
    first_round = saved.rounds[0]
    assert first_round.guesser_count == 1
    assert first_round.word_auto_picked is True
    assert first_round.end_reason == "all_guessed"
    assert first_round.wrong_guess_count == 1

    hinted = next(g for g in saved.guesses if g.round_index == 0)
    assert hinted.hints_used == 1
    assert hinted.points_spent_on_hints == price
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
        """Stands in for the word-stat writes, and restarts the room mid-way.

        These run only once the game is finished, which is exactly the window
        where the room is already reporting itself as waiting.
        """

        def __init__(self) -> None:
            self.restarted = False

        async def increment_word_offers(self, slug, words):
            if not self.restarted:
                self.restarted = True
                await flow._start_fresh_game(room, room.player_list())

        async def increment_word_stats(self, slug, word, correct, total):
            return None

    ctx.word_list_repo = RestartingWordRepo()
    room.word_list_slugs = ["english_standard"]

    await flow._start_fresh_game(room, room.player_list())
    # Two players over one round is two turns; the interference lands on the
    # second, which is the one that finishes the game.
    expected_scores: dict[str, int] = {}
    for _ in range(2):
        game = room.game
        game.force_word_choice()
        game.set_phase_deadline(game.drawing_seconds)
        guesser = next(p for p in room.player_list() if p.id != game.current_drawer)
        game.submit_guess(guesser.id, game.word)
        await flow._end_round(room)
        ctx.timers.cancel_phase_timer(room.id)
        expected_scores = {p.user_id: p.score for p in room.player_list()}
        await flow._finish_or_next(room)
    ctx.timers.cancel_phase_timer(room.id)
    await ctx.timers.close()

    assert ctx.word_list_repo.restarted, "the interleaving under test never happened"
    assert len(history.saved) == 1
    saved = history.saved[0]
    assert len(saved.rounds) == 2
    # The scores the game finished with, not the ones the restart reset to.
    assert {p.user_id: p.final_score for p in saved.participants} == expected_scores
    assert all(score > STARTING_SCORE for score in expected_scores.values())


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
