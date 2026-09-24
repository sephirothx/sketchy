"""Shared workflows used by the domain-specific Socket.IO handlers."""
from __future__ import annotations

import asyncio
import os
from math import ceil
import random
import time
import logging
from collections import Counter
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Mapping, Protocol

from app.announcements import Announcement
from app.auth.avatars import avatar_url
from app.flow_timing import timing
from app.game import MAX_HINT_SPEND, PROMPT_CHOICES_PER_TURN, Game, Phase
from app.domain_values import (
    GameOutcome,
    RuntimeEventType,
    TurnEligibilityReason,
    TurnParticipantState,
)
from app.rooms import DrawingRecapEntry, Player, Room, resolve_hint_mode
from app.services.game_highlights import build_game_highlights
from app.services.game_handoff import (
    WRITE_TIMEOUT_SECONDS,
    EnvelopeTooLarge,
    FinishedGameEnvelope,
)
from app.services.game_history import build_game_history
from app.services.runtime_metrics import metrics
from app.services.prompt_usage import tally_prompt_usage
from app.services.telemetry import telemetry
from app.presenters import (
    turn_ended_payload,
    room_state_payload,
    system_chat_message,
    turn_payload,
)
from app.prompt_content import default_prompt_list_slug
from app.prompts import letter_histogram, parse_custom_prompt_list
from app.repositories.interfaces import (
    PromptListSelectionError,
    PromptSample,
    SampledPrompt,
)

logger = logging.getLogger("sketchy.game_flow")

# Below this, lateness is scheduler jitter rather than a symptom. Recording
# every few-millisecond wobble would bury the overruns that matter.
TIMER_OVERRUN_REPORT_MS = 250

# Long enough for a healthy write on a loaded server, short enough that a hung
# database cannot pin the coroutine that ends a game. Since #541 the one
# write a room waits on is the staging of the finished game's envelope; the
# history itself is written by the handoff loop with its own budget and
# retries. The reaction path and the entry path share this bound.
HISTORY_WRITE_TIMEOUT_SECONDS = WRITE_TIMEOUT_SECONDS
#: What one stroke-heavy envelope costs a thread, measured (#976).
ENVELOPE_ENCODE_SECONDS = 0.15


def history_encode_drain_seconds() -> float:
    """What a shutdown allows for encodes still queued, on top of the write's
    own bound.

    Sized from the two things that decide it rather than guessed: every room
    this process will hold (`ROOM_GLOBAL_LIMIT`) ending in the same instant,
    at the configured pool width. A fixed ten seconds was sized for the
    ceiling the issue documented, not for the one the process enforces, and on
    a single-worker host it was less than half of what the burst needs (#976
    fifth review).
    """
    from app.deployment import history_encode_workers
    from app.services.room_quotas import DEFAULT_GLOBAL_ROOMS, _ceiling

    rooms = _ceiling(os.environ, "ROOM_GLOBAL_LIMIT", DEFAULT_GLOBAL_ROOMS)
    return ceil(rooms * ENVELOPE_ENCODE_SECONDS / max(1, history_encode_workers()))


def shutdown_cleanup_budget_seconds() -> float:
    """What a planned shutdown gives the deferred teardowns: a queued encode
    and then the write it is bounded by. Past it they are cancelled, and a
    cancelled staging counts itself as a lost game."""
    return history_encode_drain_seconds() + HISTORY_WRITE_TIMEOUT_SECONDS
# The same ten seconds the entry path and the finished-game write allow. A
# game start that cannot read its prompts must refuse rather than hang the
# host, and an unbounded database call on a request path is its own finding.
PROMPT_DRAW_TIMEOUT_SECONDS = 10
# What both start paths require before setting a game up, and what has to
# still hold once its prompts have been drawn.
MIN_PLAYERS_TO_START = 2


class _RoomStateBatch:
    """The rooms whose `room_state` an action changed, sent once it is done."""

    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        # What happened, per room, in order: the snapshot says *what* the room
        # is and these say *why*, so a client can play a sound or write a
        # line (#880, `causes`). Held with the snapshot they explain.
        self.causes: dict[str, list[dict]] = {}
        self.open = True


# One action - a command, a connect or disconnect, a timer firing - is one
# snapshot per room it touched (#880): a drawer leaving on the last turn used
# to send `game_ended`, `room_state`, `player_left`, `room_state`. The batch
# lives in a context variable so every await inside the action shares it; a
# task the action spawns inherits it too, and finds it closed if it outlives
# the action, which makes it emit directly - so no snapshot is ever dropped.
_room_state_batch: ContextVar[_RoomStateBatch | None] = ContextVar("room_state_batch", default=None)

@dataclass(frozen=True)
class _PromptDraw:
    """The prompts one game will play, with the provenance its turns record.

    An empty `pool` means no lists and no quick prompts, which the game reads
    as the built-in list - the same thing an empty room resolved to before.
    """

    pool: list[str] | None = None
    aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    version_ids: dict[str, str] = field(default_factory=dict)
    source_revision_ids_by_answer: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    source_revision_ids: tuple[str, ...] = ()
    letter_counts: dict[str, int] = field(default_factory=dict)
    letter_total: int = 0


class RoomNoLongerStartableError(RuntimeError):
    """The room stopped being able to start a game while one was being set up.

    Drawing the prompts is a database call, and seating is not held by
    `room.lock`, so the roster a caller checked can empty out underneath it.
    """


class RoomPromptResolutionError(ValueError):
    """A safe room-configuration failure for selected prompt content."""


class RoomSettingsInput(Protocol):
    """The settings a validated create or update command carries, as this service reads them.

    Declared here rather than imported from `app/handlers/payloads.py` because a
    service must not reach up into the transport package: `app.handlers` wires
    every handler domain on import, and those import this module back (#789).
    `CreateRoomPayload` and `UpdateRoomSettingsPayload` satisfy it structurally.
    `None` means "not sent" - keep the room's value. `prompt_language` is
    creation-only and read with `getattr`, so it is not part of the contract.
    """

    name: str | None
    is_public: bool | None
    max_players: int | None
    rounds: int | None
    drawing_seconds: int | None
    custom_prompts: str | None
    custom_prompts_only: bool | None
    hint_mode: str | None
    scoring_mode: str | None
    spectators_see_prompt: bool | None
    hide_masked_prompt: bool | None
    allowed_tools: list[str] | None
    color_mode: str | None
    prompt_list_slugs: list[str] | None


class GameFlowService:
    """Coordinate workflows that cross handler domains without owning registration."""

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self._sio = ctx.sio
        self._timers = ctx.timers

    async def room_settings_from_payload(
        self,
        payload: RoomSettingsInput,
        *,
        fallback: Room | None = None,
        requesting_user_id: str | None = None,
    ) -> dict:
        """Build domain settings from an already validated boundary model."""
        def value(field: str, fallback_field: str | None = None):
            parsed = getattr(payload, field)
            if parsed is not None or fallback is None:
                return parsed
            return getattr(fallback, fallback_field or field)

        # The room declares its language and the lists must agree with it
        # (R-PROMPT-02). Only creation carries the field: it is fixed for the
        # room's life, so an update reads it back off the room it is editing.
        declared_language = (
            getattr(payload, "prompt_language", None)
            or (fallback.prompt_language if fallback else "en")
        )
        scoring_mode = value("scoring_mode")
        hint_mode = value("hint_mode")
        hide_masked_prompt = value("hide_masked_prompt")
        hint_mode = resolve_hint_mode(hint_mode, scoring_mode, hide_masked_prompt)
        custom_prompts = (
            parse_custom_prompt_list(payload.custom_prompts)
            if payload.custom_prompts is not None
            else list(fallback.custom_prompts if fallback else [])
        )
        raw_slugs = getattr(payload, "prompt_list_slugs", None)
        if raw_slugs is not None and len(raw_slugs) > 0:
            prompt_list_slugs = list(raw_slugs)
        elif fallback is not None:
            prompt_list_slugs = list(fallback.prompt_list_slugs)
        else:
            prompt_list_slugs = [default_prompt_list_slug(declared_language)]

        prompt_list_revision_ids = (
            list(fallback.prompt_list_revision_ids) if fallback else []
        )
        prompt_pool_size = fallback.prompt_pool_size if fallback else 0
        prompt_letter_counts = (
            dict(fallback.prompt_letter_counts) if fallback else {}
        )
        prompt_letter_total = fallback.prompt_letter_total if fallback else 0
        # The host edits settings one change at a time, and most of those changes
        # leave the prompt lists alone; re-pinning them would cost a repository
        # round-trip per keystroke for an identical answer. An *empty* pin is
        # the exception worth asking about again - it means the read that should
        # have filled it failed, and the room would otherwise keep drawing from
        # the built-in list while the host is shown the lists they picked.
        already_pinned = (
            fallback is not None
            and prompt_list_slugs == list(fallback.prompt_list_slugs)
            and fallback.prompt_pool_size > 0
        )
        if not already_pinned and prompt_list_slugs and self._ctx.prompt_list_repo:
            try:
                if requesting_user_id is not None:
                    selection = await self._ctx.prompt_list_repo.authorize_selection(
                        prompt_list_slugs,
                        requesting_user_id=requesting_user_id,
                        expected_language=declared_language,
                    )
                else:
                    # Keep protocol-compatible adapters simple: public bundled
                    # selection has no authorization context to pass.
                    selection = await self._ctx.prompt_list_repo.authorize_selection(
                        prompt_list_slugs, expected_language=declared_language
                    )
                prompt_list_revision_ids = list(selection.revision_ids)
                prompt_pool_size = selection.prompt_count
                prompt_letter_counts = dict(selection.letter_counts)
                prompt_letter_total = selection.letter_total
            except PromptListSelectionError as error:
                raise RoomPromptResolutionError(str(error)) from error
            except Exception as error:
                if custom_prompts and value("custom_prompts_only"):
                    logger.exception(
                        "Prompt-list store unavailable for custom-only room"
                    )
                    prompt_list_revision_ids = []
                    prompt_pool_size = 0
                    prompt_letter_counts = {}
                    prompt_letter_total = 0
                else:
                    logger.exception(
                        "Failed to resolve prompts for slugs: %s", prompt_list_slugs
                    )
                    raise RoomPromptResolutionError(
                        "Prompt lists could not be loaded. Please try again."
                    ) from error

        return {
            "name": value("name"),
            "is_public": value("is_public"),
            "max_players": value("max_players"),
            "rounds": value("rounds"),
            "drawing_seconds": value("drawing_seconds"),
            "custom_prompts": custom_prompts,
            "custom_prompts_only": value("custom_prompts_only"),
            "hint_mode": hint_mode,
            "scoring_mode": scoring_mode,
            "spectators_see_prompt": value("spectators_see_prompt"),
            "hide_masked_prompt": hide_masked_prompt,
            "allowed_tools": list(value("allowed_tools")),
            "color_mode": value("color_mode"),
            "prompt_language": declared_language,
            "prompt_list_slugs": prompt_list_slugs,
            "prompt_list_revision_ids": prompt_list_revision_ids,
            "prompt_pool_size": prompt_pool_size,
            "prompt_letter_counts": prompt_letter_counts,
            "prompt_letter_total": prompt_letter_total,
        }

    async def refresh_room_prompt_selection(
        self, room: Room, *, requesting_user_id: str | None
    ) -> None:
        """Re-authorize mutable moderation state immediately before a game.

        List revisions remain immutable, but a moderator takedown is an
        operational override. Re-reading here prevents a waiting room from
        starting with content that was hidden after its settings were loaded.
        """
        if room.custom_prompts_only or not self._ctx.prompt_list_repo:
            return
        try:
            if requesting_user_id is not None:
                selection = await self._ctx.prompt_list_repo.authorize_selection(
                    list(room.prompt_list_slugs),
                    requesting_user_id=requesting_user_id,
                    expected_language=room.prompt_language,
                )
            else:
                selection = await self._ctx.prompt_list_repo.authorize_selection(
                    list(room.prompt_list_slugs), expected_language=room.prompt_language
                )
        except PromptListSelectionError as error:
            raise RoomPromptResolutionError(str(error)) from error
        except Exception as error:
            logger.exception("Failed to revalidate room prompt content")
            raise RoomPromptResolutionError(
                "Prompt lists could not be loaded. Please try again."
            ) from error
        room.prompt_list_revision_ids = list(selection.revision_ids)
        room.prompt_pool_size = selection.prompt_count
        room.prompt_letter_counts = dict(selection.letter_counts)
        room.prompt_letter_total = selection.letter_total

    def schedule_phase_timer(self, room: Room, seconds: float) -> None:
        async def _runner() -> None:
            task = asyncio.current_task()
            scheduled_at = time.monotonic()
            try:
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                return
            # How late the loop actually was. A single worker owns every room,
            # so this is the first thing that degrades under load and the last
            # thing anyone could previously see.
            late_seconds = time.monotonic() - scheduled_at - seconds
            telemetry.note_phase_timer_lateness(late_seconds)
            late_ms = int(late_seconds * 1000)
            if late_ms >= TIMER_OVERRUN_REPORT_MS:
                metrics.record(
                    RuntimeEventType.TIMER_OVERRAN,
                    room_id=room.id,
                    value=late_ms,
                    details={"phase": room.state},
                )
            # Deregister ourselves before running the timeout callback. The
            # callback (e.g. self._end_turn) may itself cancel the phase timer,
            # and without this, that call would cancel *this* still-running
            # task (since we're still registered as the phase owner), which raises
            # CancelledError into us at the next await and prevents the
            # follow-up timer (e.g. for TURN_RESULTS) from ever being scheduled
            # - silently stalling the game.
            assert task is not None
            self._timers.remove_phase_timer(room.id, task)
            try:
                async with self.room_state_batch():
                    await self._on_phase_timeout(room)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Unhandled error in phase timeout for room %s", room.id)

        self._timers.replace_phase_timer(room.id, asyncio.create_task(_runner()))

    def schedule_hint_checkpoints(self, room: Room) -> None:
        self._timers.cancel_hint_timers(room.id)
        game = room.game
        if not game or game.hint_mode != "checkpoints":
            return

        num_checkpoints = game.max_hint_checkpoints()
        if num_checkpoints <= 0:
            return

        # Distribute timed hints evenly across drawing duration based on prompt length
        interval = game.drawing_seconds / (num_checkpoints + 1)
        for i in range(1, num_checkpoints + 1):
            delay = interval * i

            async def _runner(delay=delay, game=game) -> None:
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return
                if room.game is not game or game.phase != Phase.DRAWING:
                    return
                turn_id = game.current_turn_id
                if game.reveal_hint_letter():
                    for p in room.player_list():
                        if not p.sid:
                            continue
                        # Checked again per seat, not once before the loop
                        # (#883): every emit awaits, and a turn that ends in
                        # one of those gaps used to re-mask the prompt the
                        # `turn_ended` had just revealed. The turn is named
                        # too, so a client can drop a hint for a turn it has
                        # already ended.
                        if (
                            room.game is not game
                            or game.phase != Phase.DRAWING
                            or game.current_turn_id != turn_id
                        ):
                            return
                        masked = game.masked_prompt(
                            p.id,
                            is_spectator=p.is_spectator,
                            spectators_see_prompt=room.spectators_see_prompt,
                        )
                        await self._sio.emit(
                            "hint_revealed",
                            {"maskedPrompt": masked, "turnId": turn_id},
                            to=p.sid,
                        )

            self._timers.add_hint_timer(room.id, asyncio.create_task(_runner()))

    async def _emit_room_state(self, room: Room) -> None:
        """Send the room its snapshot - at the end of the current action.

        Inside `room_state_batch` the room is only marked, and one snapshot
        goes out when the action finishes, after the action's other events:
        every listener reads the room as it ended up, and an action that
        changed it three times is one message, not three. Outside one - a
        path nothing has wrapped yet - it goes at once, as it always did.
        """
        batch = _room_state_batch.get()
        if batch is not None and batch.open:
            batch.rooms[room.id] = room
            return
        await self._send_room_state(room)

    async def _flush_room_state(self, room: Room) -> None:
        """Send a room's pending snapshot now, if the current action has one.

        For a socket that has just taken a seat: its private catch-up -
        `sync_game`, `last_game` - must land on top of the room it describes,
        and a client meets a room it did not know through its first
        `room_state`, which resets what belonged to the room before it.
        Anything the action changes after this still goes out at its end.
        """
        batch = _room_state_batch.get()
        if batch is not None and batch.open and batch.rooms.pop(room.id, None) is not None:
            await self._send_room_state(room, batch.causes.pop(room.id, None))

    async def _send_room_state(self, room: Room, causes: list[dict] | None = None) -> None:
        await self._emit_colorblind_suggestion(room)
        causes = [
            {key: value for key, value in cause.items() if key != "account"}
            for cause in causes or []
            if self._cause_still_true(room, cause)
        ]
        payload = room_state_payload(room)
        if causes:
            payload = {**payload, "causes": causes}
        await self._sio.emit("room_state", payload, room=room.id)

    async def note_cause(self, room: Room, cause: dict) -> None:
        """Say why the room's next snapshot changed: a seat came or went, or a
        line the room says about itself (#880). It rides that snapshot rather
        than being a message of its own - one action, one message per seat.
        Outside an action it goes at once, with a snapshot of its own."""
        batch = _room_state_batch.get()
        if batch is not None and batch.open:
            batch.rooms[room.id] = room
            batch.causes.setdefault(room.id, []).append(cause)
            return
        await self._send_room_state(room, [cause])

    async def note_presence(self, room: Room, event: str, player) -> None:
        """A seat `joined`, `reconnected`, `disconnected` or `left`: what the
        four presence events used to say, now said by the room's snapshot.
        `account` stays on the server: it is what `_cause_still_true` checks
        a departure against, and is stripped before anything is sent."""
        await self.note_cause(
            room,
            {
                "presence": event,
                "playerId": player.id,
                "nickname": player.nickname,
                "account": player.user_id,
            },
        )

    @staticmethod
    def _cause_still_true(room: Room, cause: dict) -> bool:
        """Whether a queued departure still describes the room it is about to
        ride (#880). An action queues it and may then await - ending a turn,
        say - and a reconnect or rejoin landing in that gap has already been
        sent with its own cause; a snapshot showing the seat back must not
        then say it went. Everything else is true when it is queued."""
        presence = cause.get("presence")
        if presence == "disconnected":
            seat = room.players.get(cause["playerId"])
            return seat is None or not seat.connected
        if presence == "left" and cause.get("account") is not None:
            return not any(seat.user_id == cause["account"] for seat in room.players.values())
        return True

    @asynccontextmanager
    async def room_state_batch(self):
        """Hold every `room_state` the enclosed action emits to its end, then
        send one per room. Nested scopes join the outer one."""
        current = _room_state_batch.get()
        if current is not None and current.open:
            yield
            return
        batch = _RoomStateBatch()
        token = _room_state_batch.set(batch)
        try:
            yield
        finally:
            _room_state_batch.reset(token)
            batch.open = False
            for room in batch.rooms.values():
                # A room the action closed has nobody left to tell.
                if self._ctx.room_manager.get_room(room.id) is room:
                    await self._send_room_state(room, batch.causes.get(room.id))

    async def _emit_colorblind_suggestion(self, room: Room) -> None:
        """Send only the host an unattributed accessibility suggestion.

        The room broadcast above intentionally carries none of this state.
        Sending an explicit inactive value lets the host remove a suggestion
        when the final opted-in player leaves or becomes a spectator.
        """
        host = next(
            (
                player
                for player in room.players.values()
                if player.is_host and player.connected and player.sid
            ),
            None,
        )
        if host is None:
            return
        # Only in the waiting room, which is the only place the palette can
        # change anyway. A suggestion the host left alone would otherwise sit
        # over the game telling them to come back to it later.
        active = bool(
            not room.colorblind_suggestion_dismissed
            and room.color_mode != "colorblind_safe"
            and room.state == "waiting"
            and not room.game
            and any(
                player.colorblind_safe_colors and not player.is_spectator
                for player in room.players.values()
            )
        )
        if room.colorblind_suggestion_sent == (host.sid, active):
            return
        room.colorblind_suggestion_sent = (host.sid, active)
        await self._sio.emit(
            "colorblind_safe_suggestion",
            {"active": active},
            to=host.sid,
        )

    async def announce(
        self,
        room: Room,
        code: Announcement,
        params: Mapping[str, object] | None = None,
        *,
        to: str | None = None,
        **flags: object,
    ) -> None:
        """Say something in the room's voice - to everyone, or to one socket.

        One payload reaches every seat, and each client writes the sentence in
        its own reader's language (R-I18N-03). Nothing here composes prose.
        """
        line = system_chat_message(code, params, **flags)
        if to is None:
            # Said to the whole room, it is why the room changed: it rides
            # the action's snapshot as a cause, the line the client writes
            # exactly as it writes a chat_message announcement (#880).
            batch = _room_state_batch.get()
            if batch is not None and batch.open:
                await self.note_cause(room, line)
                return
        await self._sio.emit(
            "chat_message",
            line,
            **({"to": to} if to else {"room": room.id}),
        )

    async def _draw_prompt_sample(self, room: Room) -> _PromptDraw:
        """Draw every prompt this game can possibly need, once, up front.

        A game starts at most `rounds x max_players` turns and offers three
        choices at each, so the whole pool was never needed - only that many
        prompts. Drawing them here rather than per turn keeps the database off
        the latency a drawer feels, and pins the content to the revisions the
        room was just authorized on: a list edited or withdrawn mid-game cannot
        rewrite a turn that is already in flight (R-LIST-07).

        The draw is weighted so it matches the merged pool it replaces. Quick
        prompts used to be concatenated with the curated ones and sampled
        together, so five of them among five hundred were five in five hundred
        and five; splitting the two halves evenly would make them far likelier
        than the host arranged. The curated half of that ratio is what the room
        can actually *draw* - `PromptSample.drawable`, which excludes answers a
        quick prompt has already claimed - and not the size of its lists, or a
        room that shadowed most of its lists would find its own prompts rarer
        than it asked for.
        """
        needed = room.rounds * room.max_players * PROMPT_CHOICES_PER_TURN
        custom = list(room.custom_prompts)

        if not custom and not room.draws_from_prompt_lists():
            # Neither lists nor quick prompts: the built-in list, as before.
            return _PromptDraw()

        # Drawn before the split, because the split needs to know how much
        # curated content there was to draw. `needed` is the most the curated
        # half could ever claim, so a prefix of this always covers it.
        sample = PromptSample()
        if room.draws_from_prompt_lists():
            try:
                sample = await asyncio.wait_for(
                    self._ctx.prompt_list_repo.sample_prompts(
                        list(room.prompt_list_revision_ids),
                        limit=needed,
                        exclude_match_keys=room.custom_prompt_match_keys(),
                    ),
                    timeout=PROMPT_DRAW_TIMEOUT_SECONDS,
                )
            except Exception as error:
                # Opening on the built-in list while the host is shown the
                # lists they chose is the failure R-LIST-06a exists to prevent,
                # so a draw that cannot be made refuses the start instead.
                logger.exception("Failed to draw prompts for room %s", room.id)
                raise RoomPromptResolutionError(
                    "Prompt lists could not be loaded. Please try again."
                ) from error

        total = len(custom) + sample.drawable
        if not total:
            # Authorization proved these lists held prompts, but moderation can
            # take the last of them away before the draw lands. Falling through
            # to the built-in list would open the room on content the host
            # never chose, and file the game as curated while it played
            # defaults - the substitution R-LIST-06a and R-LIST-08 forbid.
            logger.warning(
                "Room %s authorized prompt lists that drew nothing", room.id
            )
            raise RoomPromptResolutionError(
                "Prompt lists could not be loaded. Please try again."
            )
        indices = random.sample(range(total), min(needed, total))
        from_custom = sum(1 for index in indices if index < len(custom))
        drawn: list[SampledPrompt] = list(
            sample.prompts[: len(indices) - from_custom]
        )

        pool = random.sample(custom, from_custom) + [
            prompt.answer for prompt in drawn
        ]
        if not pool:
            # Whatever the arithmetic said, this is the state that matters: a
            # room that asked for content and has none to play. `Game` reads an
            # empty pool as the built-in list, so this is the last place the
            # forbidden substitution can be stopped.
            logger.warning("Room %s drew an empty prompt pool", room.id)
            raise RoomPromptResolutionError(
                "Prompt lists could not be loaded. Please try again."
            )
        random.shuffle(pool)

        # Only content the game can reach is priced. A room that selected lists
        # and then turned on custom-only still has them pinned, and charging
        # their letter frequencies would bill players for prompts no turn of
        # this game can show.
        letter_counts: Counter[str] = Counter()
        letter_total = 0
        if sample.drawable:
            letter_counts.update(room.prompt_letter_counts)
            letter_total += room.prompt_letter_total
        custom_counts, custom_total = letter_histogram(custom)
        letter_counts.update(custom_counts)
        letter_total += custom_total

        return _PromptDraw(
            pool=pool,
            aliases={
                prompt.answer: prompt.aliases for prompt in drawn if prompt.aliases
            },
            version_ids={
                prompt.answer: prompt.prompt_version_id
                for prompt in drawn
                if prompt.prompt_version_id is not None
            },
            source_revision_ids_by_answer={
                prompt.answer: prompt.source_revision_ids for prompt in drawn
            },
            source_revision_ids=tuple(
                revision_id
                for revision_id in room.prompt_list_revision_ids
                if any(
                    revision_id in prompt.source_revision_ids for prompt in drawn
                )
            ),
            letter_counts=dict(letter_counts),
            letter_total=letter_total,
        )

    async def _start_fresh_game(
        self,
        room: Room,
        active_players: list[Player],
        *,
        restarted: bool = False,
        seated_before: set[str] | None = None,
    ) -> None:
        """Replace any prior game with a fresh, fully synchronized game.

        Raises `RoomPromptResolutionError` if the prompts cannot be drawn, or
        `RoomNoLongerStartableError` if the room emptied while they were being
        drawn. In either case nothing here has run: everything below replaces
        the previous game, and a room left half-started would report itself as
        playing one that does not exist, refusing every later start as already
        in progress.
        """
        # Who was in the room when `active_players` was taken, so that arrivals
        # can afterwards be told from the players the caller left out on
        # purpose. It belongs to the caller because the window is theirs: the
        # roster is captured, the lists are re-authorized, and only then are
        # the prompts drawn - somebody arriving during that first await is
        # missing from the roster and present in the room, so a snapshot taken
        # here would see them as neither new nor included.
        if seated_before is None:
            seated_before = set(room.players)
        draw = await self._draw_prompt_sample(room)
        # Drawing is a database call, and seating is not held by `room.lock`,
        # so the roster the caller handed over can be stale by the time there
        # is a game to put it in. Somebody who joined in that window was seated
        # while `room.game` was still None, so nothing enrolled them; somebody
        # who left was never taken out. Reconciling here covers both, while
        # leaving out whoever the caller excluded on purpose - a player already
        # AFK is not an arrival.
        active_players = [
            player for player in active_players if player.id in room.players
        ] + [
            player
            for player in room.players.values()
            if player.id not in seated_before and not player.is_spectator
        ]
        if len(active_players) < MIN_PLAYERS_TO_START:
            # Both start paths check this before setting anything up. The draw
            # is long enough that it can stop being true in between, and a game
            # nobody checked for is not one either path agreed to start.
            raise RoomNoLongerStartableError(
                "Need at least 2 active non-AFK players to start"
            )
        if room.game is not None:
            # A restart replaces a game that never ended. Its turns were drawn
            # and guessed, and R-HIST-05 says a game that stops is recorded;
            # the first version of this simply overwrote it, and a restart
            # vote was the one way to lose a game without a trace (#993).
            # Recorded before anything below is reset, since the scores, the
            # departed seats and the recap it is made of are about to go.
            await self.record_abandoned_game(room)
        room.restart_vote = None
        room.restart_vote_cooldown_until = 0
        room.last_game_scores = []
        room.last_game_highlights = []
        room.last_game_drawings = []
        room.drawing_reactions = {}
        room.last_game_id = None
        room.last_game_history = "none"
        # Only this game's leavers matter to its history, and the room may
        # outlive many games.
        room.departed_seats = {}
        for player in room.player_list():
            player.score = 0
        room.state = "playing"
        room.game = Game(
            turn_order=[player.id for player in active_players],
            rounds_total=room.rounds,
            max_players=room.max_players,
            prompt_pool=draw.pool,
            prompt_aliases=draw.aliases,
            letter_counts=draw.letter_counts,
            letter_total=draw.letter_total,
            prompt_source_mode_value=room.prompt_source_mode(),
            drawing_seconds=room.drawing_seconds,
            hint_mode=room.hint_mode,
            scoring_mode=room.scoring_mode,
            hide_masked_prompt=room.hide_masked_prompt,
            allowed_tools=tuple(room.allowed_tools),
            color_mode=room.color_mode,
            prompt_language=room.prompt_language,
            prompt_source_revision_ids=draw.source_revision_ids,
            prompt_version_ids=draw.version_ids,
            prompt_source_revision_ids_by_answer=draw.source_revision_ids_by_answer,
            custom_prompt_keys=room.custom_prompt_match_keys(),
        )
        await self._emit_room_state(room)
        if restarted:
            await self.announce(room, Announcement.GAME_RESTARTED_BY_VOTE)
        # The room turning to play is what mounts every client's game view,
        # canvas included, so it goes before the first turn does: a
        # `turn_starting` that arrived first found no canvas to reset.
        await self._flush_room_state(room)
        # No `game_started` of its own (#880): the first `turn_starting` says so.
        await self._start_turn(room, game_started=True)

    async def _emit_canvas_sync(
        self,
        room: Room,
        sid: str,
        holds: tuple[int, int, int] | None = None,
        request_id: int = 0,
    ) -> None:
        """Answer a `request_sync_strokes`: the canvas history, or only the part
        the client is missing.

        Only ever asked for (#877). A join used to push the whole history as
        well, before its acknowledgement - on a fresh join, before the canvas
        had mounted to receive it, so the mount's own request was what loaded
        the drawing and the push was a full canvas thrown away; and on a
        rebind, a full dump to a client that already held a verified prefix.
        The client now asks when its canvas mounts and when a new socket has
        rebound its seat, claiming what it holds, so a reconnect is a tail.
        The request's own budget is the only window.

        `request_id` is echoed last on the reply: the id the client gave the
        request it is answering. The client accepts a tail only for the
        request it has outstanding, and ignores a full reply to a request it
        has abandoned (#598).

        `holds` is the client's claim about the prefix it already has, as
        (generation, actionCount, historyHash). It is verified against the
        authoritative history before it is honoured, and anything that does not
        check out - a stale generation, a count past what has been finalized, a
        hash that disagrees, a client somehow ahead of the server after an undo
        shrank the history - falls through to the full dump. The claim can only
        ever make the reply smaller, never make it wrong.
        """
        if not room.game:
            return
        canvas = room.game.canvas
        if holds is not None:
            generation, count, history_hash = holds
            claim = canvas.prefix_claim_result(generation, count, history_hash)
            telemetry.note_tail_claim(claim)
            if claim == "hit":
                await self._sio.emit(
                    "sync_strokes_tail",
                    (
                        canvas.sync_payload(count),
                        count,
                        canvas.revision,
                        canvas.generation,
                        canvas.sequence,
                        canvas.hash,
                        request_id,
                    ),
                    to=sid,
                )
                return
        if holds is None:
            telemetry.note_tail_claim("none")
        await self._sio.emit(
            "sync_strokes",
            (
                canvas.sync_payload(),
                canvas.revision,
                canvas.generation,
                canvas.sequence,
                canvas.hash,
                request_id,
            ),
            to=sid,
        )

    async def _emit_canvas_stale(
        self, room: Room, sid: str, reason: str, *, sequence: int = 0
    ) -> None:
        """Tell one socket its canvas needs recovering, once per window (#562).

        `[generation, sequence, reason, retryAfterMs]`. This replaces the full
        history the server used to push at every refused opening, undo
        disagreement and stale generation - up to the drawing budget's worth
        of 460 KB dumps per window from one socket. The client answers through
        its sync transaction, which is budgeted, carries a verified prefix when
        it can, and knows when to ask again. A notice inside the window is not
        sent again; the refusal it would have described is still counted.
        """
        if not room.game:
            return
        telemetry.note_canvas_recovery(reason)
        if not self._ctx.allow_canvas_notice(sid):
            return
        budget = self._ctx.command_budgets.for_command("request_sync_strokes")
        await self._sio.emit(
            "canvas_stale",
            [room.game.canvas.generation, sequence, reason, int(budget.window_seconds * 1000)],
            to=sid,
        )

    def canvas_commit_payload(self, room: Room, sequence: int) -> list | None:
        """`[generation, sequence, revision, historyHash]` for a committed action.

        None when the sequence is not a committed action - it was never
        committed, it has aged out of the commit window, or it is an undo,
        which has its own five-element shape and its own event. Exposed
        because a committing frame carries this alongside itself for viewers
        (§7), so the drawing handler builds it at the moment it emits.
        """
        if not room.game:
            return None
        commit = room.game.canvas.get_commit(sequence)
        if not commit or commit[2] == "undo":
            return None
        revision, history_hash, _mutation = commit
        return [room.game.canvas.generation, sequence, revision, history_hash]

    async def _emit_canvas_commit(
        self,
        room: Room,
        sequence: int,
        *,
        to: str | None = None,
    ) -> None:
        if not room.game:
            return
        commit = room.game.canvas.get_commit(sequence)
        if not commit:
            return
        revision, history_hash, mutation = commit
        if mutation == "undo":
            event = "canvas_undo"
            payload = [
                room.game.canvas.generation,
                sequence,
                revision - 1,
                revision,
                history_hash,
            ]
        else:
            event = "canvas_commit"
            payload = self.canvas_commit_payload(room, sequence)
        await self._sio.emit(
            event,
            payload,
            to=to,
            room=None if to else room.id,
        )

    async def _request_canvas_actions(
        self,
        room: Room,
        sid: str,
        expected: int,
        received: int,
    ) -> None:
        await self._sio.emit(
            "request_canvas_actions",
            [room.game.canvas.generation, expected, received],
            to=sid,
        )

    async def _sync_player_view(self, sid: str, room: Room, player, *, full: bool = True) -> None:
        """Push authoritative game state to one socket (a join, or a soft resync).

        Never the canvas (#877): the client asks for that itself, when its
        canvas mounts and when a new socket has rebound the seat, so it can
        claim the prefix it already holds. `full` is a join rather than a
        heartbeat's soft check, which is what re-sends the drawer's prompt.
        """
        game = room.game
        if not game:
            return
        if game.phase in (Phase.CHOOSING_PROMPT, Phase.DRAWING):
            await self._sio.emit(
                "sync_game",
                self._turn_payload(
                    game,
                    player,
                    room.spectators_see_prompt,
                    reactions=room.drawing_reactions_for(game.current_turn_id),
                    drawer_transport=self._drawer_transport(room),
                ),
                to=sid,
            )
            if player.id == game.current_drawer:
                if game.phase == Phase.CHOOSING_PROMPT:
                    await self._sio.emit(
                        "your_prompt_choices",
                        {
                            "choices": game.prompt_choices,
                            "seconds": round(game.remaining_seconds()),
                        },
                        to=sid,
                    )
                elif full:
                    await self._sio.emit("you_are_drawing", {"prompt": game.prompt}, to=sid)
        elif game.phase == Phase.TURN_RESULTS:
            await self._sio.emit("turn_ended", self._turn_ended_payload(room), to=sid)

    async def release_seat(
        self, sid: str, room: Room, player: Player, *, defer_durable: bool = False
    ) -> None:
        """Give up one live seat and let the room fall away behind it.

        The one way out of a room for a socket that is still connected, so
        that leaving deliberately and being moved on by an entry somewhere
        else are the same departure as far as the room is concerned: the same
        timers are cancelled, the same room state is re-emitted, and an empty
        room is torn down and its invite code retired.
        """
        self._timers.cancel_disconnect_timer(player.id)
        self._ctx.room_manager.remove_player(room, player.id)
        await self._sio.leave_room(sid, room.id)
        # Drop the room binding but keep the account: the socket stays open and
        # the player may immediately join another room as themselves. Only when
        # the session actually names this room, though - a socket giving up a
        # seat stranded somewhere else is still sitting in the room its session
        # names, and clearing that would leave it seated but unable to act.
        session = await self._sio.get_session(sid) or {}
        if session.get("room_id") == room.id:
            await self._sio.save_session(sid, {"user_id": session.get("user_id")})
        if not room.connected_players():
            self._timers.cancel_phase_timer(room.id)
            self._timers.cancel_hint_timers(room.id)
            self._timers.cancel_restart_timer(room.id)
            await self._ctx.remove_room_if_empty(room.id, defer_durable=defer_durable)
            return
        # The roster first, and sent before the game is told (#883): losing
        # the drawer starts the next turn, and a `turn_starting` that arrives
        # before the seat is gone leaves the client holding a turn whose
        # player list still has the player who left it.
        await self.note_presence(room, "left", player)
        await self._emit_room_state(room)
        await self._flush_room_state(room)
        await self._remove_player_from_game(room, player.id, defer_durable=defer_durable)
        await self._emit_room_state(room)

    async def release_other_seats(self, sid: str, *, keep: tuple[str, str] | None = None) -> None:
        """Vacate every seat this socket holds apart from the one it is taking.

        Keyed on the socket, never on the account: two tabs of one account
        sitting in two different rooms is ordinary, and only the connection
        that is moving may be moved. With no `keep`, every seat: an entry
        releases what it held *before* it makes a new room or seat (#879), so
        the old room's teardown - which can write an abandoned game and retire
        a code - is spent inside the entry's deadline rather than after a room
        already exists.
        """
        for room, player in self._ctx.room_manager.seats_for_sid(sid):
            if keep is not None and (room.id, player.id) == keep:
                continue
            logger.info(
                "socket %s gave up its seat in room %s to enter %s",
                sid,
                room.id,
                f"room {keep[0]}" if keep is not None else "another room",
            )
            # Only ever inside an entry, so the old room's durable teardown
            # is deferred rather than waited on (#879).
            await self.release_seat(sid, room, player, defer_durable=True)

    async def _join_socket_room(self, sid: str, room: Room, player, is_reconnect: bool) -> None:
        # One socket, one seat: whatever this connection was sitting in before
        # leaves by the ordinary door before it takes this one. Without it the
        # abandoned seat keeps `connected` and this very sid, which is enough
        # to stop its room ever being counted as empty - and the socket
        # session that named it has just been overwritten, so nothing would
        # ever find it again. The caller holds the socket's seating gate,
        # which is what stops a concurrent entry racing this release.
        await self.release_other_seats(sid, keep=(room.id, player.id))
        superseded_sid = player.sid if player.sid != sid else None
        player.sid = sid
        player.connected = True
        # Preserve the account bound at handshake time: the session dict is
        # replaced wholesale here, and losing user_id would strand the
        # player with no way to reconnect to their own seat.
        previous = await self._sio.get_session(sid) or {}
        await self._sio.save_session(
            sid,
            {
                "room_id": room.id,
                "player_id": player.id,
                "user_id": previous.get("user_id"),
            },
        )
        await self._sio.enter_room(sid, room.id)
        if superseded_sid:
            # Say why before cutting it off, otherwise the displaced tab
            # just freezes on a board that no longer updates.
            await self._sio.emit(
                "session_superseded",
                {"code": "opened_elsewhere", "reason": "This room was opened in another tab."},
                to=superseded_sid,
            )
            # Its disconnect handler runs inline from here, and must not wait
            # for that socket's own seating gate: two tabs reaching this seat
            # at the same moment would each be holding the gate the other
            # needs.
            with self._ctx.closing(superseded_sid):
                await self._sio.disconnect(superseded_sid)
        self._timers.cancel_disconnect_timer(player.id)
        await self._emit_room_state(room)
        # Why, before the snapshot goes: it is sent at once, for the joining
        # socket's catch-up to land on (below), and the cause rides it.
        await self.note_presence(room, "reconnected" if is_reconnect else "joined", player)
        await self._flush_room_state(room)
        await self._sync_player_view(sid, room, player)
        await self.send_last_game(sid, room)

    async def send_last_game(self, sid: str, room: Room) -> None:
        """Hand a socket arriving in a waiting room the finished game's recap.

        `room_state` no longer carries it (#871), and `game_ended` went out
        before this socket was here - a late joiner, a reconnect after the
        game ended while it was away, a tab that slept through it. Same shape
        as `game_ended`, under its own name so the client shows the recap
        without replaying the end of a game it did not watch.
        """
        payload = room.last_game_payload()
        if payload is not None:
            await self._sio.emit("last_game", payload, to=sid)

    def _drawer_transport(self, room: Room) -> str | None:
        """Which transport the drawing seat is on, for the room to pace
        playback by (R-DRAW-01).

        The transport, not the interval it resolves to. Both are facts this
        process holds, but they move on different clocks: the two cadences are
        `client_config` values an administrator can change while a turn is
        running, and every client is told the moment they do, whereas which
        transport the drawer is on changes at most once a session. Sending the
        resolved milliseconds left every viewer pacing at the old cadence
        until the next turn began; sending the transport lets each viewer
        resolve it against the config it has already been given.

        Read when a turn starts and when a socket resyncs, rather than
        tracked: the only transport change that happens is polling upgrading
        to WebSocket, which leaves a viewer pacing slower than the sender
        until that next turn - the forgiving direction rather than a free one,
        since `MAX_LAG_MS` compresses a schedule that has fallen behind rather
        than letting it drift. The reverse never occurs. `None` is a drawer
        with no socket, between reconnects, and reads as the baseline.
        """
        game = room.game
        drawer = room.players.get(game.current_drawer) if game else None
        if drawer is None or not drawer.sid:
            return None
        try:
            return str(self._sio.transport(drawer.sid))
        except Exception:
            return None

    def _turn_payload(
        self,
        game: Game,
        player: Player | None = None,
        spectators_see_prompt: bool = False,
        reactions: list[dict] | None = None,
        drawer_transport: str | None = None,
    ) -> dict:
        return turn_payload(
            game, player, spectators_see_prompt, reactions, drawer_transport
        )

    async def _start_turn(self, room: Room, *, game_started: bool = False) -> None:
        game = room.game
        assert game is not None
        afk_tokens = {p.id for p in room.player_list() if p.is_afk}
        choices = game.start_next_turn(
            afk_tokens,
            canvas_generation=room.allocate_canvas_generation(),
        )
        game.set_phase_deadline(timing.choose_prompt_seconds)
        drawer = room.players.get(game.current_drawer)
        # One message for the turn's start (#880): the new canvas identity
        # `canvas_reset` used to carry just before it, and on a game's first
        # turn the fact `game_started` used to announce.
        starting = {
            "drawerId": game.current_drawer,
            "drawerNickname": drawer.nickname if drawer else "",
            "drawerNameColor": drawer.name_color if drawer else "",
            "roundNumber": game.round_number,
            "totalRounds": game.rounds_total,
            "seconds": timing.choose_prompt_seconds,
            "canvas": [
                game.canvas.revision,
                game.canvas.generation,
                game.canvas.sequence,
                game.canvas.hash,
            ],
        }
        if game_started:
            starting["gameStarted"] = True
        await self._sio.emit("turn_starting", starting, room=room.id)
        if drawer and drawer.sid:
            await self._sio.emit(
                "your_prompt_choices",
                {"choices": choices, "seconds": timing.choose_prompt_seconds},
                to=drawer.sid,
            )
        self.schedule_phase_timer(room, timing.choose_prompt_seconds)

    async def _begin_drawing(self, room: Room) -> None:
        game = room.game
        assert game is not None
        game.snapshot_turn_participants(
            {
                player.id: (
                    TurnEligibilityReason.AFK.value
                    if player.is_afk
                    else TurnEligibilityReason.DISCONNECTED.value
                    if not player.connected
                    else TurnEligibilityReason.ELIGIBLE.value
                )
                for player in room.seated_players()
                if player.id != game.current_drawer
            }
        )
        game.set_phase_deadline(game.drawing_seconds)
        # Read once for the whole fan-out: one drawer, one transport.
        drawer_transport = self._drawer_transport(room)
        # One emit per socket, deliberately, even though at turn start every
        # guesser's payload is identical - nothing has been bought yet, so only
        # the drawer and prompt-seeing spectators actually diverge. Broadcasting
        # the guesser shape and following with a private event for the few that
        # differ saves no bytes at all (a deflate context is per connection, so
        # a broadcast is compressed once per socket regardless) and about 55-271
        # microseconds of work once every ninety seconds. Measured in
        # benchmarks/turn_start.py; the reasoning is in wire-protocol.md §5.
        for p in room.player_list():
            if not p.sid:
                continue
            await self._sio.emit(
                "turn_started",
                {
                    "turnId": game.current_turn_id,
                    "drawerId": game.current_drawer,
                    "maskedPrompt": game.masked_prompt(
                        p.id,
                        is_spectator=p.is_spectator,
                        spectators_see_prompt=room.spectators_see_prompt,
                    ),
                    "roundNumber": game.round_number,
                    "totalRounds": game.rounds_total,
                    "seconds": game.drawing_seconds,
                    "hintCost": game.hint_cost(p.id),
                    "letterPrices": game.wheel_letter_prices(p.id) if game.hint_mode == "wheel" else None,
                    "hintSpend": 0,
                    "maxHintSpend": MAX_HINT_SPEND,
                    "drawerTransport": drawer_transport,
                },
                to=p.sid,
            )
        self.schedule_phase_timer(room, game.drawing_seconds)
        self.schedule_hint_checkpoints(room)

    async def end_turn_now(self, room: Room) -> bool:
        """End the drawing phase as its own timer would have.

        The public name for what the phase timeout does, so an administrator
        command can finish a turn without reaching into a private method - and
        so it stays the *ordinary* ending: the turn scores, the results screen
        shows, and the game carries on. A room stuck behind a drawer who has
        walked away wants its turn over, not its game.
        """
        return await self._end_turn(room)

    def _settle_live_turn(self, room: Room, game: Game) -> int | None:
        """Close the drawing turn as a fact: outcomes, scores, the drawing.

        Everything `_end_turn` decides about a turn, and nothing it says
        about it - no emit, no timer - so a game recorded while a turn is
        in progress (#992: everybody walked out, or the process is draining,
        after somebody guessed) can fold that turn into its history and the
        points already on the seats have the ledger events the writer
        requires. Returns the drawer bonus, or None when there was no
        drawing turn to close.
        """
        active_eligible = {
            player.id
            for player in room.active_players()
            if game.is_turn_eligible(player.id)
        }
        all_active_guessed = bool(active_eligible) and active_eligible.issubset(
            game.correct_guessers
        )
        terminal_states = {}
        for token in game.turn_eligibility_reasons or {}:
            player = room.players.get(token)
            terminal_states[token] = (
                TurnParticipantState.LEFT.value
                if player is None
                else TurnParticipantState.AFK.value
                if player.is_afk
                else TurnParticipantState.DISCONNECTED.value
                if not player.connected
                else TurnParticipantState.ACTIVE.value
            )
        guesser_count = (
            len(active_eligible)
            if game.turn_eligibility_reasons is None
            else sum(
                reason == TurnEligibilityReason.ELIGIBLE.value
                for reason in game.turn_eligibility_reasons.values()
            )
        )
        drawer_bonus = game.end_turn(
            total_guesser_count=guesser_count,
            terminal_states=terminal_states,
            all_active_guessed=all_active_guessed,
        )
        if drawer_bonus is None:
            return None
        drawer = room.players.get(game.current_drawer)
        departed = room.departed_seats.get(game.current_drawer or "")
        if drawer:
            drawer.score += drawer_bonus
        elif departed is not None:
            # A drawer who walked out after somebody guessed still earned the
            # bonus (R-SCORE-08), and the history writer requires the seat's
            # score to sum with the ledger's `drawer_bonus` event (#992).
            departed = replace(departed, score=departed.score + drawer_bonus)
            room.departed_seats[departed.player_id] = departed
        room.record_drawing_recap(
            DrawingRecapEntry(
                # end_turn appended this turn a moment ago, so it is the one
                # being recapped. current_turn_id is never cleared and would
                # name the previous turn if these calls ever reordered.
                turn_id=game.completed_turns[-1].id,
                round_number=game.round_number,
                turn_number=len(room.last_game_drawings) + 1,
                drawer_id=game.current_drawer or "",
                drawer_nickname=(
                    drawer.nickname
                    if drawer
                    else departed.nickname
                    if departed
                    else "Unknown player"
                ),
                drawer_name_color=(
                    drawer.name_color if drawer else departed.name_color if departed else None
                ),
                prompt=game.prompt or "",
                action_count=len(game.canvas.history),
                canvas_history=game.canvas.sync_payload(),
            )
        )

        return drawer_bonus

    async def _end_turn(self, room: Room) -> bool:
        game = room.game
        if not game or game.phase != Phase.DRAWING:
            return False
        self._timers.cancel_phase_timer(room.id)
        self._timers.cancel_hint_timers(room.id)
        drawer_bonus = self._settle_live_turn(room, game)
        if drawer_bonus is None:
            return False
        # Before the payload is built: `seconds` on it is
        # `game.remaining_seconds()`, which without this still answers for the
        # drawing phase that just ended. A turn that ran out of clock therefore
        # announced a results phase of 0 seconds, and one that ended early
        # because everyone guessed announced whatever drawing time was left -
        # 200 seconds for a 5 second screen. The countdown the client draws
        # from it was wrong in both directions.
        game.set_phase_deadline(timing.turn_results_seconds)
        await self._sio.emit(
            "turn_ended",
            self._turn_ended_payload(room, drawer_bonus=drawer_bonus),
            room=room.id,
        )
        self.schedule_phase_timer(room, timing.turn_results_seconds)
        return True

    def _turn_ended_payload(self, room: Room, drawer_bonus: int | None = None) -> dict:
        return turn_ended_payload(room, drawer_bonus)

    async def record_abandoned_game(self, room: Room, *, defer_durable: bool = False) -> bool:
        """Write down a game that stopped without ending, and clear it.

        Every way a game can be lost funnels through here, which it has to:
        the first version of this lived in `_remove_player_from_game` alone,
        and the common case - everybody closing their tab - never reaches that.
        The eviction path removes the last player and tears the room down
        directly, so the game it was holding went unrecorded, which is the
        whole thing #323 set out to fix.

        Snapshotted before the room is cleared, for the same reason the
        finished path snapshots: what follows discards the state the history is
        made of. Returns whether anything was recorded, so a caller can tell a
        room that held a game from one that did not.
        """
        game = room.game
        if game is None:
            return False
        if game.phase == Phase.DRAWING and game.correct_guessers:
            # Somebody guessed the turn in progress: their points are on
            # their seat, and the history writer proves every seat's score
            # against the ledger (R-HIST-12). Closed as a fact so the ledger
            # has the turn those points came from (#992).
            self._settle_live_turn(room, game)
        history = (
            build_game_history(
                room,
                game,
                finished_at=datetime.now(timezone.utc),
                outcome=GameOutcome.ABANDONED.value,
            )
            if self._ctx.game_history_repo
            else None
        )
        metrics.record(
            RuntimeEventType.GAME_ABANDONED,
            room_id=room.id,
            details={"round_number": game.round_number},
        )
        room.game = None
        self._note_history_write_started(room, game, history)
        envelope = FinishedGameEnvelope(history) if history else None
        # On its own task for the same reason as at the end of a game: the
        # room is told what happened without waiting for the write about it.
        self._ctx.defer_cleanup(self._hand_off_finished_game(room, envelope))
        return True

    def _note_history_write_started(self, room: Room, game: Game, history) -> None:
        """Tell the room which game it just held and whether a row is coming.

        A reaction given from the recap is a write to that game's row, so the
        handler has to know the row exists before trying (see
        `handlers/reactions.py`). Set before the first await after
        `room.game = None`, so no reaction can observe a room that has
        forgotten its game but not yet said what became of it.
        """
        room.last_game_id = game.id
        room.last_game_history = (
            "pending"
            if history is not None and self._ctx.finished_games is not None
            else "unrecorded"
        )

    async def _hand_off_finished_game(
        self, room: Room, envelope: FinishedGameEnvelope | None
    ) -> None:
        """Stage a finished game for the handoff loop: the one write a room waits on.

        Runs after the room has been told the game ended, and is bounded,
        because a database that is slow or down must not keep a room from
        ending its game. The envelope is history, drawings and prompt usage
        together (#541); once it is staged the loop owns it, retries it, and
        reports back through `note_history_outcome`. If staging itself fails
        the game is lost, and that is counted exactly as a lost write was:
        there is nothing a player could do about it either way.
        """
        worker = self._ctx.finished_games
        if worker is None or envelope is None:
            # `_note_history_write_started` already said "unrecorded".
            return
        started = time.monotonic()
        try:
            # The encode is not inside the bound (#976): it is CPU on the
            # envelope pool, and a burst of endings queueing there must cost
            # latency rather than games. The bound is for the write.
            staged = await worker.encode(envelope)
            await asyncio.wait_for(
                worker.stage_encoded(staged), timeout=HISTORY_WRITE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(
                "Timed out staging game history for room %s after %ss",
                room.id,
                HISTORY_WRITE_TIMEOUT_SECONDS,
            )
            self._note_abandoned_write(room, "handoff", "timeout", started)
            self.note_history_outcome(envelope.game_id, "failed", room=room)
        except asyncio.CancelledError:
            # The shutdown drain gave up on this task. Counted like any other
            # lost write before it goes, rather than disappearing with the
            # process (#976 fourth review).
            logger.error("Staging game history for room %s was cancelled", room.id)
            self._note_abandoned_write(room, "handoff", "cancelled", started)
            self.note_history_outcome(envelope.game_id, "failed", room=room)
            raise
        except EnvelopeTooLarge as error:
            logger.error("Game %s for room %s cannot be staged: %s", envelope.game_id, room.id, error)
            self._note_abandoned_write(room, "handoff", "too_large", started)
            self.note_history_outcome(envelope.game_id, "failed", room=room)
        except Exception:
            logger.exception("Failed to stage game history for room %s", room.id)
            self._note_abandoned_write(room, "handoff", "error", started)
            self.note_history_outcome(envelope.game_id, "failed", room=room)

    def note_history_outcome(
        self, game_id: str, state: str, *, room: Room | None = None
    ) -> None:
        """Record how a game's write went - for the room that still calls it its last.

        Called by the handoff loop when a replay ends ("recorded" or
        "failed"), and here when staging fails. A rematch can start and be
        abandoned while the loop is still working, so an outcome arriving
        after the room has moved on to a newer game must not speak for it:
        it would mark a row still being written as recorded, or a recorded
        one as failed. Without a room in hand, the room is found by the
        game it last held; a room that is gone has nobody left to tell.
        """
        rooms = [room] if room is not None else list(self._ctx.room_manager.rooms.values())
        for candidate in rooms:
            if candidate.last_game_id == game_id:
                candidate.last_game_history = state

    @staticmethod
    def _note_abandoned_write(room: Room, kind: str, reason: str, started: float) -> None:
        """Make a swallowed write countable (#482).

        Swallowing is right - nothing a player can do, and a slow database
        must not hold a room open - but a loss that leaves only a log line is
        a loss nobody can alert on or reconcile. One observation, carrying
        which write and why, on both the persisted recorder and the process
        counters, so the rate is visible to a scraper and on the operations
        page alike.
        """
        elapsed_ms = int((time.monotonic() - started) * 1000)
        metrics.record(
            RuntimeEventType.HISTORY_WRITE_ABANDONED,
            room_id=room.id,
            value=elapsed_ms,
            details={"kind": kind, "reason": reason},
        )
        telemetry.history_write_abandoned(kind, reason)

    def _prompt_usage_for(self, game: Game, *, occurred_at: datetime):
        """A finished game's prompt-list facts, or None when it has none.

        The whole game is one batch keyed by the game's id (R-HIST-01), and
        it rides in the same envelope as the history so the two are staged
        together and replayed under one manifest (#541).
        """
        revision_ids = game.prompt_source_revision_ids
        if not self._ctx.prompt_list_repo or not revision_ids:
            return None, ()
        usage = tally_prompt_usage(
            game.completed_turns,
            batch_id=game.id,
            occurred_at=occurred_at,
            scoring_mode=game.scoring_mode,
            hint_mode=game.hint_mode,
        )
        if not usage:
            return None, ()
        return usage, tuple(revision_ids)

    async def _finish_or_next(self, room: Room, *, defer_durable: bool = False) -> None:
        game = room.game
        assert game is not None
        if game.is_finished():
            finished_at = datetime.now(timezone.utc)
            # Snapshot the result before anything is touched or awaited.
            # Everything below mutates the room and then yields, and the
            # room is already reporting itself as waiting by then - so a
            # `start_game` landing in one of those gaps would reset scores
            # and departed seats out from under a history built later.
            history = (
                build_game_history(
                    room, game, finished_at=finished_at
                )
                if self._ctx.game_history_repo
                else None
            )
            metrics.record(
                RuntimeEventType.GAME_FINISHED,
                room_id=room.id,
                value=max(0, int((finished_at - game.started_at).total_seconds())),
                details={"total_rounds": game.rounds_total},
            )
            # Snapshotted for the same reason: the room is an editable
            self._timers.cancel_restart_timer(room.id)
            room.restart_vote = None
            room.restart_vote_cooldown_until = 0
            room.state = "waiting"
            room.game = None
            self._note_history_write_started(room, game, history)
            usage, revision_ids = self._prompt_usage_for(game, occurred_at=finished_at)
            envelope = FinishedGameEnvelope(history, usage, revision_ids) if history else None
            # Always on its own task (#976 fourth review), never inside the
            # action: a game ends inside a `room_state_batch`, so awaiting the
            # handoff here put the encode - deliberately unbounded, so that a
            # burst of endings costs latency rather than games - in front of
            # the room's own snapshot. Nothing a player is waiting to see is
            # behind it: the task runs at the next suspension, which is the
            # `game_ended` below. Created *before* the shutdown coordinator
            # is told the game is over (#994): the drain counts a room with
            # no game as drained and `drain_room_cleanups` returns at once
            # when nothing is tracked, so a staging created after either
            # look ran on a task nobody waited for, and a deploy landing on
            # the last turn's results screen lost the game without a trace.
            self._ctx.defer_cleanup(self._hand_off_finished_game(room, envelope))
            if self._ctx.shutdown is not None:
                self._ctx.shutdown.notify_game_state_changed()
            # An account that left and rejoined holds the points of both
            # seats, here as in the record (R-HIST-12, #992): the standings
            # a room is shown and the ones it is written with agree.
            carried: dict[str, int] = {}
            for seat in room.departed_seats.values():
                if seat.user_id and not seat.is_spectator:
                    carried[seat.user_id] = carried.get(seat.user_id, 0) + seat.score
            standings = [
                {
                    "playerId": p.id,
                    "nickname": p.nickname,
                    "nameColor": p.name_color,
                    "avatarUrl": avatar_url(p.avatar_key),
                    "isAnonymous": p.is_anonymous,
                    "score": p.score + (carried.get(p.user_id, 0) if p.user_id else 0),
                }
                for p in room.player_list()
            ]
            # Ordered by the score each entry carries, not the seat's alone:
            # the podium is read off this order, and a seat holding 100 of
            # its account's 500 belongs above one holding 300 (review of
            # #1047).
            room.last_game_scores = sorted(standings, key=lambda entry: -entry["score"])
            # Built from the snapshot above, before the emit and before any
            # await, for the same reason the scores are: by the time anything
            # yields, the room is an editable waiting room again.
            room.last_game_highlights = build_game_highlights(room, game)

            # No await between the snapshot above and this emit, so a
            # `start_game` cannot land in between and blank the scores the
            # room is about to be shown.
            await self._sio.emit("game_ended", room.last_game_payload(), room=room.id)
            await self._emit_room_state(room)
        else:
            await self._start_turn(room)

    async def _abandon_current_turn(self, room: Room, *, defer_durable: bool = False) -> None:
        """Give up the turn in progress: move to the next one, or end the game.

        `_start_turn` on its own walks `turn_index` past the final turn,
        which plays a turn the room never asked for and reports it as round
        `rounds_total + 1`. `_finish_or_next` is what chooses between
        advancing and ending, so every caller that drops a live turn goes
        through here rather than reaching for `_start_turn` directly.

        The phase timer is cancelled explicitly because ending the game
        never reaches `_start_turn`, and so never reaches the
        `replace_phase_timer` that would otherwise have retired it.
        """
        if not room.game:
            return
        self._timers.cancel_phase_timer(room.id)
        self._timers.cancel_hint_timers(room.id)
        await self._finish_or_next(room, defer_durable=defer_durable)

    def _privileged_sids(
        self,
        room: Room,
        game: Game,
        *,
        exclude_sid: str | None = None,
    ) -> list[str]:
        """Return sids of players who may see spectator chat during this turn:
        the drawer, all correct guessers, and all spectators.
        """
        return [
            p.sid
            for p in room.player_list()
            if p.sid
            and p.sid != exclude_sid
            and (
                p.id in game.correct_guessers
                or p.id == game.current_drawer
                or p.is_spectator
            )
        ]

    async def apply_afk_consequences(self, room: Room, player: Player) -> None:
        """Move the turn along after `player`'s AFK flag was just raised.

        An AFK drawer forfeits the turn; an AFK guesser is one fewer player the
        turn is still waiting on, which may already be all of them.
        """
        game = room.game
        if not game or room.state != "playing":
            return
        if player.is_afk and player.id == game.current_drawer:
            if game.phase == Phase.CHOOSING_PROMPT:
                await self._abandon_current_turn(room)
            elif game.phase == Phase.DRAWING:
                await self._end_turn(room)
        else:
            await self._end_turn_if_all_guessed(room)

    async def _end_turn_if_all_guessed(self, room: Room) -> None:
        """End the drawing phase early when every eligible guesser has guessed correctly."""
        game = room.game
        if not game or game.phase != Phase.DRAWING:
            return
        active_eligible = {
            player.id
            for player in room.active_players()
            if game.is_turn_eligible(player.id)
        }
        had_eligible_guesser = (
            any(
                reason == TurnEligibilityReason.ELIGIBLE.value
                for reason in game.turn_eligibility_reasons.values()
            )
            if game.turn_eligibility_reasons is not None
            else bool(active_eligible)
        )
        if had_eligible_guesser and active_eligible.issubset(game.correct_guessers):
            await self._end_turn(room)

    async def _on_phase_timeout(self, room: Room) -> None:
        game = room.game
        if not game:
            return
        if game.phase == Phase.CHOOSING_PROMPT:
            game.force_prompt_choice()
            await self._begin_drawing(room)
        elif game.phase == Phase.DRAWING:
            await self._end_turn(room)
        elif game.phase == Phase.TURN_RESULTS:
            await self._finish_or_next(room)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def _remove_player_from_game(
        self, room: Room, token: str, *, defer_durable: bool = False
    ) -> None:
        """`defer_durable` is an entry taking this seat away (#879): the game
        transition happens here, its history staging on its own."""
        game = room.game
        if not game:
            return
        if (
            token == game.current_drawer
            and game.phase == Phase.DRAWING
            and game.correct_guessers
        ):
            # Somebody already guessed: the points are on their seat and the
            # drawing exists, so this is a turn that ended, not one that never
            # happened. Abandoning it dropped the turn from `completed_turns`
            # while the points stayed on the seats, and the ledger the history
            # writer proves against no longer summed to the scores - every game
            # with a mid-turn walkout was refused (#992). Ended the way the
            # clock ends one, the way an AFK drawer's turn already is - and
            # before the rotation loses the seat, because removing the drawer
            # rewinds the cursor to before the next survivor, and a turn
            # recorded after that carries round 0.
            await self._end_turn(room)
        was_drawer = game.remove_player_from_rotation(token)
        if not game.turn_order:
            self._timers.cancel_phase_timer(room.id)
            self._timers.cancel_hint_timers(room.id)
            self._timers.cancel_restart_timer(room.id)
            room.restart_vote = None
            room.state = "waiting"
            await self.record_abandoned_game(room, defer_durable=defer_durable)
            if self._ctx.shutdown is not None:
                self._ctx.shutdown.notify_game_state_changed()
        elif was_drawer and game.phase != Phase.TURN_RESULTS:
            await self._abandon_current_turn(room, defer_durable=defer_durable)
        elif was_drawer:
            # The turn just ended - above, or by its own clock a moment ago.
            # The results screen runs its course and its timer moves the game
            # on from the cursor the removal left; cutting it short showed
            # the next turn under a results screen nobody had read.
            pass
        else:
            await self._end_turn_if_all_guessed(room)

    async def _existing_player_for_sid(self, sid: str, room_id: str) -> Player | None:
        """If this socket already has a live session in the target room, return its player.

        Guards against duplicate create/join calls from the same connection (e.g. a
        client re-invoking an effect) spawning a duplicate "ghost" player.
        """
        session = await self._ctx.sio.get_session(sid)
        if not session or session.get("room_id") != room_id:
            return None
        room = self._ctx.room_manager.get_room(room_id)
        if not room:
            return None
        player = room.players.get(session.get("player_id"))
        return player if player and player.sid == sid and player.connected else None

    async def require_current_player(self, sid: str) -> tuple[Room, Player] | None:
        """Resolve an authenticated room member and reject superseded sockets."""
        session = await self._ctx.sio.get_session(sid) if sid else None
        room = self._ctx.room_manager.get_room(session.get("room_id")) if session else None
        player = room.players.get(session.get("player_id")) if room and session else None
        if not room or not player or not player.connected or player.sid != sid:
            return None
        return room, player
