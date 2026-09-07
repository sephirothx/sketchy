"""Persisting a finished game: what is recorded, and what deliberately is not."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import socketio

from app.game import MAX_GUESS_POINTS, MIN_GUESS_POINTS
from app.handlers import register_all_handlers as register_handlers
from app.prompts import PROMPTS
from app.services import game_flow
from tests.fake_game_history_repo import FakeGameHistoryRepository
from tests.handlers.helpers import (
    StubPromptListRepo,
    build_context,
    build_room,
    play_to_completion,
    replay_staged,
    replay_through_backoff,
    staged_rows,
)

pytestmark = pytest.mark.asyncio


def attach_curated_sources(room, *revision_ids: str) -> None:
    """Pin the room to revisions its game will draw curated prompts from.

    The version IDs themselves come from the draw now, so the room only carries
    the pin and the size that weights it; `CuratedPromptListRepository` answers
    with the built-in prompts and a stable version ID for each.
    """
    room.prompt_list_revision_ids = list(revision_ids or ("revision-standard",))
    room.prompt_list_slugs = room.prompt_list_slugs or ["english_standard"]
    room.prompt_pool_size = len(PROMPTS)


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
    correct = [
        (turn.id, outcome)
        for turn in saved.turns
        for outcome in turn.participant_outcomes
        if outcome.outcome == "correct"
    ]
    assert len(correct) == 4
    assert {turn_id for turn_id, _ in correct} == {turn.id for turn in saved.turns}
    assert saved.record.score_ledger_version == 1
    assert [event.event_order for event in saved.score_events] == list(
        range(1, len(saved.score_events) + 1)
    )
    ledger_totals = {
        participant.seat_id: sum(
            event.points_delta
            for event in saved.score_events
            if event.participant_seat_id == participant.seat_id
        )
        for participant in saved.participants
    }
    assert ledger_totals == {
        participant.seat_id: participant.final_score
        for participant in saved.participants
    }


async def test_seat_without_an_account_is_fully_preserved():
    room_manager, room, players = build_room(
        rounds=1,
        accounts={"Ann": "user-ann", "Bob": "user-bob", "Cid": None},
    )
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    saved = history.saved[0]
    assert {p.user_id for p in saved.participants} == {
        "user-ann",
        "user-bob",
        None,
    }
    assert saved.record.player_count == len(saved.participants) == 3
    assert len(saved.turns) == 3
    cid = next(participant for participant in saved.participants if participant.user_id is None)
    assert cid.display_name == "Cid"
    assert cid.seat_id
    assert any(
        turn.drawer_user_id is None and turn.drawer_seat_id == cid.seat_id
        for turn in saved.turns
    )
    assert any(
        outcome.user_id is None and outcome.seat_id == cid.seat_id
        and outcome.outcome == "correct"
        for turn in saved.turns
        for outcome in turn.participant_outcomes
    )


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
    await replay_staged(ctx)

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


async def test_a_game_everyone_walks_out_of_is_still_recorded():
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
    await replay_staged(ctx)

    assert room.game is None
    # This used to be thrown away. `_persist_game_history` ran only for a game
    # that finished, so the games a maintainer most wants to look at - the ones
    # that fell apart - were the only ones leaving no trace at all.
    assert len(history.saved) == 1
    written = history.saved[0]
    assert written.record.outcome == "abandoned"
    # Only the turn that was actually played, and it still ended at a knowable
    # time: finished_at means when the game stopped, not that it finished.
    assert len(written.turns) == 1
    assert written.record.finished_at is not None


async def test_one_account_and_one_accountless_seat_are_recorded():
    room_manager, room, players = build_room(
        rounds=1, accounts={"Ann": "user-ann", "Bob": None}
    )
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    assert len(history.saved) == 1
    assert len(history.saved[0].participants) == 2
    assert history.saved[0].record.player_count == 2


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
    await replay_staged(ctx)

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
    guesser = next(p for p in room.player_list() if p.id != game.current_drawer)
    game.snapshot_turn_participants({guesser.id: "eligible"})
    game.set_phase_deadline(game.drawing_seconds)

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
    await replay_staged(ctx)

    saved = history.saved[0]
    first_round = saved.turns[0]
    assert first_round.guesser_count == 1
    assert first_round.prompt_auto_picked is True
    assert first_round.end_reason == "all_guessed"
    assert first_round.wrong_guess_count == 1

    outcome = first_round.participant_outcomes[0]
    assert outcome.eligible is True
    assert outcome.eligibility_reason == "eligible"
    assert outcome.outcome == "correct"
    assert outcome.terminal_state == "active"
    # What lands in history is what the player actually banked: net of hints.
    assert outcome.points_awarded == awarded == gross - price
    assert outcome.correct_guess_time_seconds is not None
    assert outcome.wrong_guess_count == 1
    assert outcome.hints_used == 1
    assert outcome.points_spent_on_hints == price

    first_turn_events = [
        event for event in saved.score_events if event.turn_id == first_round.id
    ]
    assert [event.event_type for event in first_turn_events] == [
        "guess_award",
        "hint_charge",
        "drawer_bonus",
    ]
    assert [event.points_delta for event in first_turn_events] == [
        gross,
        -price,
        awarded,
    ]
    # Rule versions are the game's, once (#552): the events carry none.
    assert saved.record.scoring_version == game.scoring_version

    # Both players were in the rotation for both turns.
    assert {p.turns_played for p in saved.participants} == {2}


async def test_no_scoring_game_has_outcomes_but_no_hypothetical_score_events():
    room_manager, room, _ = build_room(rounds=1)
    room.scoring_mode = "none"
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, room.player_list())

    saved = history.saved[0]
    assert saved.record.score_ledger_version == 1
    assert saved.score_events == []
    assert all(participant.final_score == 0 for participant in saved.participants)
    assert all(
        outcome.outcome == "correct"
        for turn in saved.turns
        for outcome in turn.participant_outcomes
    )


async def test_a_player_who_never_guesses_correctly_keeps_attempt_and_hint_facts():
    room_manager, room, _ = build_room(rounds=1)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)
    flow = ctx.game_flow

    await flow._start_fresh_game(room, room.player_list())
    game = room.game
    game.hint_mode = "purchase"
    game.force_prompt_choice()
    await flow._begin_drawing(room)
    guesser = next(p for p in room.player_list() if p.id != game.current_drawer)
    assert game.buy_hint_letter(guesser.id, 0) is True
    assert game.submit_guess(guesser.id, "definitely wrong") == (False, 0)
    await flow._end_turn(room)
    ctx.timers.cancel_phase_timer(room.id)
    await flow._finish_or_next(room)

    while room.game is not None:
        game = room.game
        game.force_prompt_choice()
        await flow._begin_drawing(room)
        await flow._end_turn(room)
        ctx.timers.cancel_phase_timer(room.id)
        await flow._finish_or_next(room)
    await ctx.timers.close()
    await replay_staged(ctx)

    first_turn = history.saved[0].turns[0]
    outcome = first_turn.participant_outcomes[0]
    assert outcome.outcome == "incorrect"
    assert outcome.points_awarded is None
    assert outcome.correct_guess_time_seconds is None
    assert outcome.wrong_guess_count == 1
    assert outcome.hints_used == 1
    assert outcome.points_spent_on_hints > 0


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

    # The staging insert is the one write that runs once the game is
    # finished - exactly the window where the room is already reporting
    # itself as waiting - so the restart is made to land inside it.
    store = ctx.finished_games.store
    original_stage = store.stage
    interleaving = {"restarted": False}

    async def restarting_stage(staged, *, now):
        if not interleaving["restarted"]:
            interleaving["restarted"] = True
            await flow._start_fresh_game(room, room.player_list())
        return await original_stage(staged, now=now)

    store.stage = restarting_stage
    ctx.prompt_list_repo = StubPromptListRepo(PROMPTS)
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
    await replay_staged(ctx)

    assert interleaving["restarted"], "the interleaving under test never happened"
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


async def test_a_write_that_lost_its_lock_is_tried_again_by_the_loop():
    """A lock wait past the web role's budget is transient: a deletion or a
    rebuild held the seat's account for a moment. The game stays staged and
    is written on a later attempt rather than given up as unrecorded (#541)."""
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository(lost_locks=2)
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    # Staged, one attempt made and lost, the row handed back with a wait.
    assert history.attempts == 1
    assert history.saved == []
    assert room.last_game_history == "pending"
    [row] = staged_rows(ctx).values()
    assert row.state == "pending" and row.attempts == 1
    assert row.next_attempt_at > ctx.handoff_clock.now

    await replay_staged(ctx)
    assert history.attempts == 1, "not due yet: the backoff is honoured"

    await replay_through_backoff(ctx, 2)
    assert history.attempts == 3
    assert len(history.saved) == 1
    assert staged_rows(ctx) == {}
    assert room.last_game_history == "recorded"


async def test_a_write_that_keeps_failing_is_given_up_and_counted(signals):
    from app.services.game_handoff import MAX_ATTEMPTS

    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository(lost_locks=100)
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)
    await replay_through_backoff(ctx, MAX_ATTEMPTS + 2)

    assert history.attempts == MAX_ATTEMPTS
    assert history.saved == []
    assert room.last_game_history == "failed"
    [row] = staged_rows(ctx).values()
    assert (row.state, row.failure_code) == ("failed", "exhausted")
    assert row.payload is None, "a failed row keeps no content"
    assert [lost_write(event) for event in abandoned_writes()] == [
        {"kind": "replay", "reason": "exhausted"}
    ]
    assert signals.history_writes_abandoned.get(("replay", "exhausted")) == 1


async def test_a_refused_write_is_left_staged_for_the_loop():
    """An ordinary failure used to be final. Now it is a wait: the envelope
    is the record, and nothing is counted as lost until the loop gives up."""
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository(fail=True)
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    assert history.attempts == 1
    assert room.last_game_history == "pending"
    assert abandoned_writes() == []


async def test_a_conflicting_game_is_given_up_at_once(signals):
    """The database already holds this id with different content: the
    second attempt would find the same thing, so there is no second attempt."""
    room_manager, room, players = build_room(rounds=1)
    history = FakeGameHistoryRepository(conflict=True)
    ctx = build_context(room_manager, history)

    await play_to_completion(ctx, room, players)

    assert history.attempts == 1
    assert room.last_game_history == "failed"
    [row] = staged_rows(ctx).values()
    assert (row.state, row.failure_code, row.payload) == ("failed", "conflict", None)
    assert signals.history_writes_abandoned.get(("replay", "conflict")) == 1


async def test_history_is_skipped_entirely_without_a_repository():
    room_manager, room, players = build_room(rounds=1)
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.emit = AsyncMock()
    sio.get_session = AsyncMock(return_value=None)
    sio.save_session = AsyncMock()

    await play_to_completion(ctx, room, players)

    assert room.state == "waiting"


class FakeWordListRepository(StubPromptListRepo):
    """Records the batched write, and can stand in for a locked database.

    Draws from the built-in prompts so a game started against it plays real
    curated content, with one stable version ID per prompt - which is what the
    usage write is keyed by.
    """

    def __init__(self, *, timeline=None, hang=False):
        super().__init__(PROMPTS)
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
    """A locked database must cost the counters, not the room. The room
    never waits on the usage write at all now: it is staged with the game
    and written by the loop, whose own hang is bounded and retried."""
    from app.services import game_handoff

    room_manager, room, players = build_room(rounds=1)
    room.prompt_list_slugs = ["english_standard"]
    attach_curated_sources(room)
    words = FakeWordListRepository(hang=True)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history, words)

    with patch.object(game_handoff, "REPLAY_TIMEOUT_SECONDS", 0.05):
        await play_to_completion(ctx, room, players)

    assert words.calls == [], "the hung writes never landed"
    # The history half of the envelope is done; only the usage is owed.
    assert len(history.saved) == 1
    [row] = staged_rows(ctx).values()
    assert (row.history_state, row.usage_state, row.state) == ("done", "pending", "pending")
    # The room was still told the game ended, with the real standings rather
    # than the blank list a racing `start_game` would have left behind.
    payload = emitted_payload(ctx, "game_ended")
    assert payload is not None
    assert [entry["nickname"] for entry in payload["scores"]]
    assert room.state == "waiting"

    # Once the database answers, the retry writes the usage and only the
    # usage: the history is not written twice.
    words._hang = False
    await replay_through_backoff(ctx, 1)
    assert len(words.calls) == 1
    assert len(history.saved) == 1
    assert staged_rows(ctx) == {}


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
    """A room's own "apple" is not the curated "apple", and must not credit it.

    The two share display text and nothing else. The curated twin is shadowed
    out of the draw entirely, so no turn can offer it and no usage row can
    reach the prompt version behind it.
    """
    room_manager, room, players = build_room(rounds=1)
    room.custom_prompts = ["apple"]
    room.prompt_list_slugs = ["english_standard"]
    words = FakeWordListRepository()
    words.prompts = ["apple", "banana", "castle"]
    words.prompt_version_ids = {
        prompt: f"version-{index}" for index, prompt in enumerate(words.prompts)
    }
    attach_curated_sources(room)

    room.prompt_pool_size = len(words.prompts)
    custom_collision_id = words.prompt_version_ids["apple"]
    ctx = build_context(room_manager, FakeGameHistoryRepository(), words)

    await play_to_completion(ctx, room, players)

    assert len(words.calls) == 1
    _, usage = words.calls[0]
    assert custom_collision_id not in usage.offers
    assert custom_collision_id not in usage.picks
    assert sum(usage.offers.values()) == 4  # two curated offers over two turns


async def test_a_game_everyone_closes_their_tab_on_is_recorded():
    """The way a game is actually lost: nobody leaves, they all just go.

    The eviction path removes the last player and tears the room down without
    passing through `_remove_player_from_game`, so a version of this that only
    hooked the latter recorded nothing at all - which is the case #323 exists
    for.
    """
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

    # Everyone's grace window runs out, which is what closing a tab becomes.
    for player in list(room.player_list()):
        room_manager.remove_player(room, player.id)
    assert not room.connected_players()
    await ctx.remove_room_if_empty(room.id)
    await ctx.timers.close()
    await replay_staged(ctx)

    assert room_manager.get_room(room.id) is None
    assert len(history.saved) == 1
    written = history.saved[0]
    assert written.record.outcome == "abandoned"
    assert len(written.turns) == 1


async def test_a_room_closed_without_a_game_records_nothing():
    """An empty waiting room is not an abandoned game."""
    room_manager, room, players = build_room(rounds=2)
    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history)

    for player in list(room.player_list()):
        room_manager.remove_player(room, player.id)
    await ctx.remove_room_if_empty(room.id)
    await ctx.timers.close()
    await replay_staged(ctx)

    assert history.saved == []


# --- #482: a swallowed write is counted, with its reason -----------------------


def abandoned_writes() -> list:
    """The `history.write_abandoned` observations recorded since the last drain."""
    from app.domain_values import RuntimeEventType
    from app.services.runtime_metrics import metrics

    return [
        event
        for event in metrics.drain()
        if event.event_type == RuntimeEventType.HISTORY_WRITE_ABANDONED.value
    ]


def lost_write(event) -> dict:
    """Which write and why; a replay's event also names the game."""
    return {key: event.details[key] for key in ("kind", "reason")}


@pytest.fixture
def signals(monkeypatch):
    from app.services.runtime_metrics import metrics
    from app.services.telemetry import Telemetry

    from app.services import game_handoff

    store = Telemetry()
    monkeypatch.setattr(game_flow, "telemetry", store)
    monkeypatch.setattr(game_handoff, "telemetry", store)
    metrics.drain()
    yield store
    metrics.drain()


async def test_a_game_that_cannot_be_staged_is_counted_as_an_error(signals):
    """The one write the room waits on. A database that refuses it loses
    the game, and that is recorded exactly as a lost write always was."""
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    ctx.finished_games.store.fail_stage = RuntimeError("database unavailable")

    await play_to_completion(ctx, room, players)

    events = abandoned_writes()
    assert [event.details for event in events] == [{"kind": "handoff", "reason": "error"}]
    assert events[0].room_id == room.id
    assert signals.history_writes_abandoned.get(("handoff", "error")) == 1
    assert room.last_game_history == "failed"
    # And the game still ended for the players.
    assert room.state == "waiting"


async def test_a_staging_that_hung_is_counted_as_a_timeout(signals):
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    ctx.finished_games.store.hang_stage = True

    with patch.object(game_flow, "HISTORY_WRITE_TIMEOUT_SECONDS", 0.05):
        await play_to_completion(ctx, room, players)

    events = abandoned_writes()
    assert [event.details for event in events] == [{"kind": "handoff", "reason": "timeout"}]
    assert events[0].value >= 50
    assert signals.history_writes_abandoned.get(("handoff", "timeout")) == 1
    assert room.state == "waiting"


async def test_a_replay_that_hung_is_retried_not_counted_as_lost(signals):
    """A staged game outlives a hung write: the attempt is bounded, the row
    is handed back, and nothing is lost until the loop gives up."""
    from app.services import game_handoff

    room_manager, room, players = build_room(rounds=1)

    class HungRepo(FakeGameHistoryRepository):
        async def save_game(self, *args):
            self.attempts += 1
            await asyncio.sleep(3600)

    history = HungRepo()
    ctx = build_context(room_manager, history)
    with patch.object(game_handoff, "REPLAY_TIMEOUT_SECONDS", 0.05):
        await play_to_completion(ctx, room, players)

    assert abandoned_writes() == []
    assert signals.history_replays.get(("retried",)) == 1
    assert room.last_game_history == "pending"
    [row] = staged_rows(ctx).values()
    assert row.state == "pending" and row.attempts == 1


async def test_a_usage_write_that_conflicts_is_given_up_without_touching_the_history(signals):
    """Facts already recorded stay recorded (R-PRIV-06): a conflicting usage
    batch fails the envelope, and the history half written before it is
    neither undone nor written again."""
    from app.repositories.interfaces import PromptUsageConflictError

    room_manager, room, players = build_room(rounds=1)
    attach_curated_sources(room)

    class ConflictingWords(FakeWordListRepository):
        async def record_prompt_usage(self, prompt_list_revision_ids, usage):
            raise PromptUsageConflictError("different facts under this batch id")

    history = FakeGameHistoryRepository()
    ctx = build_context(room_manager, history, ConflictingWords())
    await play_to_completion(ctx, room, players)

    assert len(history.saved) == 1
    [row] = staged_rows(ctx).values()
    assert (row.state, row.failure_code, row.history_state) == ("failed", "conflict", "done")
    assert [lost_write(event) for event in abandoned_writes()] == [
        {"kind": "replay", "reason": "conflict"}
    ]
    assert signals.history_writes_abandoned.get(("replay", "conflict")) == 1


async def test_a_write_that_lands_is_not_counted_as_lost(signals):
    room_manager, room, players = build_room(rounds=1)
    ctx = build_context(room_manager, FakeGameHistoryRepository())
    await play_to_completion(ctx, room, players)
    assert abandoned_writes() == []
    assert signals.history_writes_abandoned.total() == 0
