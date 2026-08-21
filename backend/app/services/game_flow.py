"""Shared workflows used by the domain-specific Socket.IO handlers."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.game import (
    CHOOSE_PROMPT_SECONDS,
    MAX_HINT_SPEND,
    TURN_RESULTS_SECONDS,
    Game,
    Phase,
)
from app.handlers.sessions import (
    existing_player_for_sid as resolve_existing_player_for_sid,
    require_current_player as resolve_current_player,
)
from app.handlers.payloads import (
    CreateRoomPayload,
    UpdateRoomSettingsPayload,
)
from app.rooms import DrawingRecapEntry, Player, Room, resolve_hint_mode
from app.services.game_history import build_game_history
from app.services.prompt_usage import tally_prompt_usage
from app.presenters import (
    turn_ended_payload,
    room_state_payload,
    system_chat_message,
    turn_payload,
)
from app.prompts import parse_custom_prompt_list

logger = logging.getLogger("sketchy.game_flow")

RECONNECT_GRACE_SECONDS = 30
# Long enough for a healthy write on a loaded server, short enough that a hung
# database cannot pin the coroutine that ends a game.
HISTORY_WRITE_TIMEOUT_SECONDS = 10
# Prompt-usage metrics are a separate transaction from the history write, so
# they get their own budget - but the same ceiling, so the two post-game
# writes together cannot pin the coroutine for longer than a player would
# wait before reloading anyway.
PROMPT_USAGE_WRITE_TIMEOUT_SECONDS = 10

class GameFlowService:
    """Coordinate workflows that cross handler domains without owning registration."""

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self._sio = ctx.sio
        self._timers = ctx.timers

    async def room_settings_from_payload(
        self,
        payload: CreateRoomPayload | UpdateRoomSettingsPayload,
        *,
        fallback: Room | None = None,
    ) -> dict:
        """Build domain settings from an already validated boundary model."""
        def value(field: str, fallback_field: str | None = None):
            parsed = getattr(payload, field)
            if parsed is not None or fallback is None:
                return parsed
            return getattr(fallback, fallback_field or field)

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
            prompt_list_slugs = ["english_standard"]

        curated_prompts: list[str] = []
        if prompt_list_slugs and self._ctx.prompt_list_repo:
            try:
                curated_prompts = await self._ctx.prompt_list_repo.get_prompts_by_slugs(prompt_list_slugs)
            except Exception:
                logger.exception("Failed to load prompts for slugs: %s", prompt_list_slugs)

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
            "spectators_see_solution": value("spectators_see_solution"),
            "hide_masked_prompt": hide_masked_prompt,
            "prompt_list_slugs": prompt_list_slugs,
            "curated_prompts": curated_prompts,
        }

    def schedule_phase_timer(self, room: Room, seconds: float) -> None:
        async def _runner() -> None:
            task = asyncio.current_task()
            try:
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                return
            # Deregister ourselves before running the timeout callback. The
            # callback (e.g. self._end_round) may itself cancel the phase timer,
            # and without this, that call would cancel *this* still-running
            # task (since we're still registered as the phase owner), which raises
            # CancelledError into us at the next await and prevents the
            # follow-up timer (e.g. for TURN_RESULTS) from ever being scheduled
            # - silently stalling the game.
            assert task is not None
            self._timers.remove_phase_timer(room.id, task)
            try:
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
                if game.reveal_hint_letter():
                    for p in room.player_list():
                        if not p.sid:
                            continue
                        masked = game.masked_prompt(
                            p.id,
                            is_spectator=p.is_spectator,
                            spectators_see_solution=room.spectators_see_solution,
                        )
                        await self._sio.emit(
                            "hint_revealed",
                            {"maskedPrompt": masked},
                            to=p.sid,
                        )

            self._timers.add_hint_timer(room.id, asyncio.create_task(_runner()))

    async def _emit_room_state(self, room: Room) -> None:
        await self._sio.emit("room_state", room_state_payload(room), room=room.id)

    async def announce(self, room: Room, text: str, *, to: str | None = None) -> None:
        """Say something in the room's voice - to everyone, or to one socket."""
        await self._sio.emit(
            "chat_message",
            system_chat_message(text),
            **({"to": to} if to else {"room": room.id}),
        )

    async def _start_fresh_game(
        self,
        room: Room,
        active_players: list[Player],
        *,
        restarted: bool = False,
    ) -> None:
        """Replace any prior game with a fresh, fully synchronized game."""
        room.restart_vote = None
        room.restart_vote_cooldown_until = 0
        room.last_game_scores = []
        room.last_game_drawings = []
        # Only this game's leavers matter to its history, and the room may
        # outlive many games.
        room.departed_seats = {}
        for player in room.player_list():
            player.score = 0
        room.state = "playing"
        room.game = Game(
            turn_order=[player.id for player in active_players],
            rounds_total=room.rounds,
            prompt_pool=room.effective_prompt_pool(),
            drawing_seconds=room.drawing_seconds,
            hint_mode=room.hint_mode,
            scoring_mode=room.scoring_mode,
            hide_masked_prompt=room.hide_masked_prompt,
        )
        await self._emit_room_state(room)
        if restarted:
            await self.announce(room, "The game was restarted by player vote.")
        game_started_payload = {"restarted": True} if restarted else {}
        await self._sio.emit("game_started", game_started_payload, room=room.id)
        await self._start_turn(room)

    async def _emit_canvas_sync(self, room: Room, sid: str) -> None:
        if not room.game:
            return
        await self._sio.emit(
            "sync_strokes",
            (
                room.game.canvas.sync_payload(),
                room.game.canvas.revision,
                room.game.canvas.generation,
                room.game.canvas.sequence,
                room.game.canvas.hash,
            ),
            to=sid,
        )

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
        event = "canvas_undo" if mutation == "undo" else "canvas_commit"
        payload = (
            [
                room.game.canvas.generation,
                sequence,
                revision - 1,
                revision,
                history_hash,
            ]
            if mutation == "undo"
            else [
                room.game.canvas.generation,
                sequence,
                revision,
                history_hash,
            ]
        )
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

    async def _sync_player_view(self, sid: str, room: Room, player, *, sync_canvas: bool = True) -> None:
        """Push authoritative game/canvas state to one socket (join or soft resync)."""
        game = room.game
        if not game:
            return
        if game.phase in (Phase.CHOOSING_PROMPT, Phase.DRAWING):
            await self._sio.emit(
                "sync_game",
                self._turn_payload(game, player, room.spectators_see_solution),
                to=sid,
            )
            if sync_canvas:
                await self._emit_canvas_sync(room, sid)
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
                elif sync_canvas:
                    await self._sio.emit("you_are_drawing", {"prompt": game.prompt}, to=sid)
        elif game.phase == Phase.TURN_RESULTS:
            await self._sio.emit("turn_ended", self._turn_ended_payload(room), to=sid)

    async def _join_socket_room(self, sid: str, room: Room, player, is_reconnect: bool) -> None:
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
                {"reason": "This room was opened in another tab."},
                to=superseded_sid,
            )
            await self._sio.disconnect(superseded_sid)
        self._timers.cancel_disconnect_timer(player.id)
        await self._emit_room_state(room)
        event_name = "player_reconnected" if is_reconnect else "player_joined"
        await self._sio.emit(
            event_name,
            {"playerId": player.id, "nickname": player.nickname},
            room=room.id,
        )
        await self._sync_player_view(sid, room, player)

    def _turn_payload(self, game: Game, player: Player | None = None, spectators_see_solution: bool = False) -> dict:
        return turn_payload(game, player, spectators_see_solution)

    async def _start_turn(self, room: Room) -> None:
        game = room.game
        assert game is not None
        afk_tokens = {p.id for p in room.player_list() if p.is_afk}
        choices = game.start_next_turn(
            afk_tokens,
            canvas_generation=room.allocate_canvas_generation(),
        )
        game.set_phase_deadline(CHOOSE_PROMPT_SECONDS)
        drawer = room.players.get(game.current_drawer)
        await self._sio.emit(
            "canvas_reset",
            [
                game.canvas.revision,
                game.canvas.generation,
                game.canvas.sequence,
                game.canvas.hash,
            ],
            room=room.id,
        )
        await self._sio.emit(
            "turn_starting",
            {
                "drawerId": game.current_drawer,
                "drawerNickname": drawer.nickname if drawer else "",
                "drawerNameColor": drawer.name_color if drawer else "",
                "roundNumber": game.round_number,
                "totalRounds": game.rounds_total,
                "seconds": CHOOSE_PROMPT_SECONDS,
            },
            room=room.id,
        )
        if drawer and drawer.sid:
            await self._sio.emit(
                "your_prompt_choices",
                {"choices": choices, "seconds": CHOOSE_PROMPT_SECONDS},
                to=drawer.sid,
            )
        self.schedule_phase_timer(room, CHOOSE_PROMPT_SECONDS)

    async def _begin_drawing(self, room: Room) -> None:
        game = room.game
        assert game is not None
        game.set_phase_deadline(game.drawing_seconds)
        for p in room.player_list():
            if not p.sid:
                continue
            await self._sio.emit(
                "turn_started",
                {
                    "drawerId": game.current_drawer,
                    "maskedPrompt": game.masked_prompt(
                        p.id,
                        is_spectator=p.is_spectator,
                        spectators_see_solution=room.spectators_see_solution,
                    ),
                    "roundNumber": game.round_number,
                    "totalRounds": game.rounds_total,
                    "seconds": game.drawing_seconds,
                    "hintCost": game.hint_cost(p.id),
                    "letterPrices": game.wheel_letter_prices(p.id) if game.hint_mode == "wheel" else None,
                    "hintSpend": 0,
                    "hintBudget": MAX_HINT_SPEND,
                },
                to=p.sid,
            )
        self.schedule_phase_timer(room, game.drawing_seconds)
        self.schedule_hint_checkpoints(room)

    async def _end_round(self, room: Room) -> bool:
        game = room.game
        if not game or game.phase != Phase.DRAWING:
            return False
        self._timers.cancel_phase_timer(room.id)
        self._timers.cancel_hint_timers(room.id)
        guesser_count = len(room.eligible_guessers())
        drawer_bonus = game.end_round(total_guesser_count=guesser_count)
        if drawer_bonus is None:
            return False
        drawer = room.players.get(game.current_drawer)
        if drawer:
            drawer.score += drawer_bonus
        room.record_drawing_recap(
            DrawingRecapEntry(
                round_number=game.round_number,
                turn_number=len(room.last_game_drawings) + 1,
                drawer_id=game.current_drawer or "",
                drawer_nickname=drawer.nickname if drawer else "Unknown player",
                drawer_name_color=drawer.name_color if drawer else None,
                prompt=game.prompt or "",
                action_count=len(game.canvas.history),
                canvas_history=game.canvas.sync_payload(),
            )
        )

        await self._sio.emit(
            "turn_ended",
            self._turn_ended_payload(room, drawer_bonus=drawer_bonus),
            room=room.id,
        )
        self.schedule_phase_timer(room, TURN_RESULTS_SECONDS)
        return True

    def _turn_ended_payload(self, room: Room, drawer_bonus: int | None = None) -> dict:
        return turn_ended_payload(room, drawer_bonus)

    async def _persist_game_history(self, room: Room, history) -> None:
        """Write a finished game's snapshot: the only write this epic makes.

        Runs after the room has been told the game ended, and is bounded,
        because a database that is slow or down must not keep a room from
        ending its game. Failure is logged and swallowed for the same
        reason: there is nothing a player could do about it.
        """
        if not self._ctx.game_history_repo or history is None:
            return
        try:
            await asyncio.wait_for(
                self._ctx.game_history_repo.save_game(
                    history.record,
                    history.participants,
                    history.turns,
                    history.guesses,
                ),
                timeout=HISTORY_WRITE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # save_game runs in one transaction, so the cancellation this
            # raises rolls the partial write back rather than leaving half
            # a game behind.
            logger.error(
                "Timed out persisting game history for room %s after %ss",
                room.id,
                HISTORY_WRITE_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to persist game history for room %s", room.id)

    async def _record_prompt_usage(
        self,
        room: Room,
        game: Game,
        prompt_list_slugs: list[str],
    ) -> None:
        """Fold a finished game's prompts into the prompt-list metrics.

        Runs after the room has been told the game ended, and is bounded,
        for the same reasons as `_persist_game_history`: nothing a player
        can see depends on these counters, so a database that is slow or
        locked must not be able to hold a room open waiting for them.

        The whole game goes in one call, and the repository writes it in
        one transaction. Failure is logged and swallowed, like the history
        write: there is nothing a player could do about it.
        """
        if not self._ctx.prompt_list_repo or not prompt_list_slugs:
            return
        usage = tally_prompt_usage(game.completed_turns)
        if not usage:
            return
        try:
            await asyncio.wait_for(
                self._ctx.prompt_list_repo.record_prompt_usage(prompt_list_slugs, usage),
                timeout=PROMPT_USAGE_WRITE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Timed out recording prompt usage for room %s after %ss",
                room.id,
                PROMPT_USAGE_WRITE_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("Failed to record prompt usage for room %s", room.id)

    async def _finish_or_next(self, room: Room) -> None:
        game = room.game
        assert game is not None
        if game.is_finished():
            # Snapshot the result before anything is touched or awaited.
            # Everything below mutates the room and then yields, and the
            # room is already reporting itself as waiting by then - so a
            # `start_game` landing in one of those gaps would reset scores
            # and departed seats out from under a history built later.
            history = (
                build_game_history(
                    room, game, finished_at=datetime.now(timezone.utc)
                )
                if self._ctx.game_history_repo
                else None
            )
            # Snapshotted for the same reason: the room is an editable
            # waiting room again by the time the metrics are written, so
            # the host can change its prompt lists out from under them.
            prompt_list_slugs = list(room.prompt_list_slugs)
            self._timers.cancel_restart_timer(room.id)
            room.restart_vote = None
            room.restart_vote_cooldown_until = 0
            room.state = "waiting"
            room.game = None
            room.last_game_scores = [
                {
                    "playerId": p.id,
                    "nickname": p.nickname,
                    "nameColor": p.name_color,
                    "isAnonymous": p.is_anonymous,
                    "score": p.score,
                }
                for p in sorted(room.player_list(), key=lambda p: -p.score)
            ]

            # No await between the snapshot above and this emit, so a
            # `start_game` cannot land in between and blank the scores the
            # room is about to be shown.
            await self._sio.emit(
                "game_ended",
                {
                    "scores": room.last_game_scores,
                    "drawings": room.drawing_recap_metadata(),
                },
                room=room.id,
            )
            await self._emit_room_state(room)
            # Last, so that nothing a player is waiting to see is behind a
            # database round trip.
            await self._persist_game_history(room, history)
            await self._record_prompt_usage(room, game, prompt_list_slugs)
        else:
            await self._start_turn(room)

    async def _abandon_current_turn(self, room: Room) -> None:
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
        await self._finish_or_next(room)

    def _privileged_sids(
        self,
        room: Room,
        game: Game,
        *,
        exclude_sid: str | None = None,
    ) -> list[str]:
        """Return sids of players who may see restricted in-round chat:
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

        An AFK drawer forfeits the turn; an AFK guesser is one fewer answer the
        round is still waiting on, which may already be all of them.
        """
        game = room.game
        if not game or room.state != "playing":
            return
        if player.is_afk and player.id == game.current_drawer:
            if game.phase == Phase.CHOOSING_PROMPT:
                await self._abandon_current_turn(room)
            elif game.phase == Phase.DRAWING:
                await self._end_round(room)
        else:
            await self._end_round_if_all_guessed(room)

    async def _end_round_if_all_guessed(self, room: Room) -> None:
        """End the drawing phase early when every eligible guesser has guessed correctly."""
        game = room.game
        if not game or game.phase != Phase.DRAWING:
            return
        guesser_count = len(room.eligible_guessers())
        if game.all_guessed(guesser_count):
            await self._end_round(room)

    async def _on_phase_timeout(self, room: Room) -> None:
        game = room.game
        if not game:
            return
        if game.phase == Phase.CHOOSING_PROMPT:
            game.force_prompt_choice()
            await self._begin_drawing(room)
        elif game.phase == Phase.DRAWING:
            await self._end_round(room)
        elif game.phase == Phase.TURN_RESULTS:
            await self._finish_or_next(room)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def _remove_player_from_game(self, room: Room, token: str) -> None:
        game = room.game
        if not game:
            return
        was_drawer = game.remove_player_from_rotation(token)
        if not game.turn_order:
            self._timers.cancel_phase_timer(room.id)
            self._timers.cancel_hint_timers(room.id)
            self._timers.cancel_restart_timer(room.id)
            room.restart_vote = None
            room.state = "waiting"
            room.game = None
        elif was_drawer:
            await self._abandon_current_turn(room)

    async def _existing_player_for_sid(self, sid: str, room_id: str) -> Player | None:
        """If this socket already has a live session in the target room, return its player.

        Guards against duplicate create/join calls from the same connection (e.g. a
        client re-invoking an effect) spawning a duplicate "ghost" player.
        """
        return await resolve_existing_player_for_sid(self._ctx, sid, room_id)

    async def require_current_player(self, sid: str) -> tuple[Room, Player] | None:
        """Resolve an authenticated room member and reject superseded sockets."""
        return await resolve_current_player(self._ctx, sid)

