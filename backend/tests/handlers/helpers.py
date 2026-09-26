"""Helpers shared by the handler test modules."""
from __future__ import annotations

import asyncio
import random
from unittest.mock import AsyncMock

import socketio
from datetime import datetime, timedelta, timezone

from app.game import Game
from app.handlers import register_all_handlers as register_handlers
from app.services.game_handoff import FinishedGameHandoffWorker
from tests.fake_envelope_store import MemoryEnvelopeStore
from app.domain_values import AGNOSTIC_PROMPT_LANGUAGE
from app.prompt_content import prompt_match_key
from app.prompts import letter_histogram
from app.repositories.interfaces import (
    MixedRoomListError,
    PinnedPromptSelection,
    PromptListSelectionError,
    PromptSample,
    PromptTranslation,
    SampledPrompt,
)
from app.rooms import RoomManager

# Keys that identify a player to the server. None of them may appear in
# anything broadcast to other players.
_CREDENTIAL_KEYS = {
    "reconnectSecret",
    "reconnect_secret",
    "sessionToken",
    "userId",
    "user_id",
}


def canvas_action(game: Game, sequence: int, nonce: int | None = None) -> list[int]:
    """The [generation, sequence, nonce] a draw payload is stamped with. The
    nonce defaults to the sequence, so stamping the same number twice is a
    resend of one action; pass a different nonce for a fresh action."""
    return [game.canvas.generation, sequence, sequence if nonce is None else nonce]


def contains_secret(value, secret: str) -> bool:
    """Whether a payload leaks a credential, by value or by telltale key.

    The credential is now the opaque token in the session cookie rather than a per-room
    secret, but the property being guarded is unchanged: nothing that
    identifies a player to the server may appear in anything broadcast to
    other players.
    """
    if value == secret:
        return True
    if isinstance(value, dict):
        return any(
            key in _CREDENTIAL_KEYS or contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(contains_secret(item, secret) for item in value)
    return False


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


class ManualClock:
    """The handoff worker's idea of now, moved by hand through the backoff."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


def build_context(room_manager, history_repo, prompt_list_repo=None, timeline=None):
    sio = socketio.AsyncServer(async_mode="asgi")
    # The handoff runs against an in-memory queue here (#541): a game is
    # staged by the flow and replayed into the fake repositories by
    # `replay_staged`, which `play_to_completion` calls on its way out. The
    # worker's clock is the test's to move, so a backoff is a call rather
    # than a wait.
    clock = ManualClock()
    finished_games = (
        FinishedGameHandoffWorker(
            MemoryEnvelopeStore(),
            game_history_repo=history_repo,
            prompt_list_repo=prompt_list_repo,
            clock=clock,
        )
        if history_repo is not None
        else None
    )
    ctx = register_handlers(
        sio,
        room_manager,
        game_history_repo=history_repo,
        prompt_list_repo=prompt_list_repo,
        finished_games=finished_games,
    )
    if finished_games is not None:
        finished_games.bind_outcome(ctx.game_flow.note_history_outcome)
    ctx.handoff_clock = clock
    if timeline is None:
        sio.emit = AsyncMock()
    else:
        async def _record(event, *_args, **_kwargs):
            timeline.append(("emit", event))

        sio.emit = AsyncMock(side_effect=_record)
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
        game.force_prompt_choice()
        # What `_begin_drawing` does: freeze who may guess, so the turn ends
        # with an outcome per seat and the award has a row to ride on (#548).
        game.snapshot_turn_participants(
            {p.id: "eligible" for p in room.player_list() if p.id != game.current_drawer}
        )
        game.set_phase_deadline(game.drawing_seconds)
        for player in room.player_list():
            if player.id == game.current_drawer:
                continue
            if guessers is not None and player.nickname not in guessers:
                continue
            correct, points = game.submit_guess(player.id, game.prompt)
            if correct:
                # Mirror the chat handler's score mutation; the flow service
                # separately applies the drawer bonus at turn end.
                player.score += points
        await flow._end_turn(room)
        ctx.timers.cancel_phase_timer(room.id)
        await flow._finish_or_next(room)
    await ctx.timers.close()
    await replay_staged(ctx)


async def settle_deferred(ctx):
    """Wait for the writes an action handed to its own tasks (#879, #976).

    A finished game is staged on a tracked task, not inside the action, so
    that the room's own snapshot never waits behind an encode. A test that
    wants to look at the staging waits for it here, as the shutdown drain
    does in the process.
    """
    while ctx.room_cleanups:
        await asyncio.gather(*list(ctx.room_cleanups), return_exceptions=True)


async def settle_capacity_closes(ctx):
    """Wait for every socket turned away for capacity to be closed (#998).

    The close is a task that sleeps `SERVER_FULL_CLOSE_SECONDS` from when it
    first runs, not from when the handshake scheduled it. A fixed sleep of the
    delay plus a margin raced it: on a loaded runner fifty tasks created in one
    burst start late enough that the later ones were still asleep when the test
    looked. Waited on here instead, with a deadline that only a close that never
    comes would reach.
    """
    closes = set(ctx._capacity_closes)
    if not closes:
        return
    done, pending = await asyncio.wait(closes, timeout=5.0)
    assert not pending, f"{len(pending)} capacity closes still pending after 5 s"
    for task in done:
        task.result()


async def replay_staged(ctx):
    """Run the handoff loop's work once: every staged game, replayed now.

    What the supervised loop does in the process the moment it is woken;
    here it is a call, so a test sees the write land - or fail - before it
    looks. A test that wants to look between staging and replay simply does
    not call this.
    """
    await settle_deferred(ctx)
    worker = ctx.finished_games
    if worker is None:
        return None
    return await worker.drain()


async def replay_through_backoff(ctx, rounds: int):
    """Move the worker's clock past every backoff step and replay each time."""
    for _ in range(rounds):
        ctx.handoff_clock.advance(3600)
        await replay_staged(ctx)


def staged_rows(ctx) -> dict:
    return ctx.finished_games.store.rows


class SessionStore:
    """Socket sessions that persist, for flows that cross rooms.

    ``AsyncServer.save_session`` is mocked away in most handler tests because
    nothing reads it back. A socket moving between rooms does, and the value
    it reads has to be the one the previous handler wrote.
    """

    def __init__(self, *, accounts: bool = True) -> None:
        self.sessions: dict[str, dict] = {}
        # Opening a room needs a provisioned session, so an unseeded socket
        # gets an account of its own - one per sid, because a test that uses
        # two sids means two people unless it says otherwise.
        self._accounts = accounts

    def account_for(self, sid: str) -> str | None:
        return f"user-{sid}" if self._accounts else None

    async def get(self, sid, namespace=None) -> dict:
        return self.sessions.setdefault(sid, {"user_id": self.account_for(sid)})

    async def save(self, sid, session, namespace=None) -> None:
        self.sessions[sid] = dict(session)


class StubPromptListRepo:
    """A prompt-list store backed by a fixed set of prompts.

    Answers both halves of the split the live repository makes: pinning, which
    a waiting room is admitted by and which reads no prompt text, and drawing,
    which a starting game takes its sample from. Holding one list and deriving
    both keeps a test from asserting against a pool the draw would never
    produce. `reads` counts pins so a test can show when one was avoided.
    """

    def __init__(
        self,
        prompts=("aardvark", "zeppelin"),
        language="en",
        *,
        revision_ids=(),
        aliases=None,
        prompt_version_ids=None,
        concept_ids=None,
        translations=None,
    ):
        self.prompts = list(prompts)
        # By answer: a prompt's form in each room language, for a stub that
        # plays mixed-language rooms (#1182). A prompt left out is agnostic.
        self.translations = dict(translations or {})
        # By answer; a prompt left out is drawn with no concept, and keyed by
        # its answer as a quick prompt is.
        self.concept_ids = dict(concept_ids or {})
        self.language = language
        self.revision_ids = tuple(revision_ids)
        self.aliases = dict(aliases or {})
        # Curated content always carries a version identity, and usage is keyed
        # by it - a stub without one records nothing and quietly passes tests
        # about what was recorded.
        self.prompt_version_ids = dict(
            prompt_version_ids
            if prompt_version_ids is not None
            else {
                prompt: f"version-{index}"
                for index, prompt in enumerate(self.prompts)
            }
        )
        self.reads = 0
        self.draws = 0

    def _match_key(self, prompt: str) -> str:
        return prompt_match_key(
            prompt, self.language if self.language != "mul" else "en"
        )

    async def authorize_selection(
        self, slugs, *, requesting_user_id=None, expected_language=None
    ):
        self.reads += 1
        # The live store refuses a selection that is not in the room's declared
        # language (R-PROMPT-02); a stub that answered anyway would let a test
        # pass on a room the server would never have opened.
        # A language-agnostic stub list (#821) answers to any room, as the
        # live store's does; a mixed room (#1182) takes a stub that spells its
        # prompts in every language, or holds only agnostic ones.
        if expected_language == "mul":
            if self.language != AGNOSTIC_PROMPT_LANGUAGE and not self.translations:
                raise MixedRoomListError("A mixed-language room cannot use this list")
        elif expected_language is not None and self.language not in (
            expected_language,
            AGNOSTIC_PROMPT_LANGUAGE,
        ):
            raise PromptListSelectionError(
                "Selected prompt lists are not in this room's language"
            )
        counts, total = letter_histogram(self.prompts)
        by_language = {}
        if expected_language == "mul":
            # Each language priced from its own spellings, as the live store
            # prices it from its own lists.
            for language in {l for spelled in self.translations.values() for l in spelled}:
                by_language[language] = letter_histogram(
                    [spelled[language] for spelled in self.translations.values() if language in spelled]
                )
        return PinnedPromptSelection(
            slugs=tuple(slugs),
            language=expected_language or self.language,
            revision_ids=self.revision_ids,
            prompt_count=len(self.prompts),
            letter_counts=counts,
            letter_total=total,
            letter_counts_by_language={l: c for l, (c, _) in by_language.items()},
            letter_total_by_language={l: t for l, (_, t) in by_language.items()},
        )

    async def sample_prompts(
        self, revision_ids, *, limit, exclude_match_keys=(), exclude_language=None
    ):
        self.draws += 1
        # Keys in another fold are not compared, as in the live store.
        excluded = (
            set(exclude_match_keys)
            if exclude_language in (None, self.language)
            else set()
        )
        drawable = [
            prompt
            for prompt in self.prompts
            if self._match_key(prompt) not in excluded
        ]
        # Shuffled for the same reason the real draw is random: a caller that
        # only ever sees a stable prefix cannot show that it mixes properly.
        random.shuffle(drawable)
        return PromptSample(
            prompts=tuple(
                SampledPrompt(
                    answer=prompt,
                    match_key=self._match_key(prompt),
                    aliases=self.aliases.get(prompt, ()),
                    prompt_version_id=self.prompt_version_ids.get(prompt),
                    source_revision_ids=tuple(revision_ids),
                    concept_id=self.concept_ids.get(prompt),
                )
                for prompt in drawable[:limit]
            ),
            drawable=len(drawable),
        )

    async def sample_mixed_prompts(self, revision_ids, *, limit):
        self.draws += 1
        drawable = list(self.prompts)
        random.shuffle(drawable)
        return PromptSample(
            prompts=tuple(
                SampledPrompt(
                    answer=prompt,
                    match_key=self._match_key(prompt),
                    prompt_version_id=self.prompt_version_ids.get(prompt),
                    source_revision_ids=tuple(revision_ids),
                    concept_id=self.concept_ids.get(prompt),
                    translations={
                        language: PromptTranslation(
                            answer=answer,
                            prompt_version_id=f"{self.prompt_version_ids.get(prompt)}-{language}",
                            source_revision_ids=tuple(revision_ids),
                        )
                        for language, answer in self.translations.get(prompt, {}).items()
                    },
                )
                for prompt in drawable[:limit]
            ),
            drawable=len(drawable),
        )

    async def record_prompt_usage(self, revision_ids, usage):
        return None


def room_lines(emit) -> list[dict]:
    """Every line the room said, however it travelled: a `chat_message`, or a
    cause riding a `room_state` (#880) - the client writes both the same way."""
    lines: list[dict] = []
    for call in emit.await_args_list:
        if not call.args:
            continue
        if call.args[0] == "chat_message":
            lines.append(call.args[1])
        elif call.args[0] == "room_state":
            lines.extend(c for c in call.args[1].get("causes", []) if "presence" not in c)
    return lines
