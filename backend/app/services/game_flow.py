"""Shared workflows used by the domain-specific Socket.IO handlers."""
from __future__ import annotations

import asyncio
import logging

from app.game import (
    CHOOSE_WORD_SECONDS,
    ROUND_END_SECONDS,
    Game,
    Phase,
)
from app.handlers.auth import (
    existing_player_for_sid as resolve_existing_player_for_sid,
    require_current_player as resolve_current_player,
)
from app.handlers.payloads import (
    CreateRoomPayload,
    HintPayload,
    JoinRoomPayload,
    PayloadError,
    PlayerSettingsPayload,
    RecapDrawingPayload,
    RoomPreviewPayload,
    SelectWordPayload,
    TextPayload,
    ToggleAfkPayload,
    UpdateRoomSettingsPayload,
    VotePayload,
    WheelLetterPayload,
    parse_draw_payload,
    parse_empty_payload,
    parse_payload,
    parse_undo_payload,
)
from app.rooms import (
    DrawingRecapEntry,
    Player,
    Room,
    RoomFullError,
    STARTING_SCORE,
    normalize_name_color,
)
from app.presenters import (
    editable_room_settings_payload,
    round_ended_payload,
    room_state_payload,
    session_payload,
    turn_payload,
)
from app.words import MAX_WORD_LENGTH, parse_custom_word_list

logger = logging.getLogger("sketchy.game_flow")

RECONNECT_GRACE_SECONDS = 30

class GameFlowService:
    """Coordinate workflows that cross handler domains without owning registration."""

    def __init__(self, ctx) -> None:
        sio = ctx.sio
        room_manager = ctx.room_manager
        timer_manager = ctx.timers

        def room_settings_from_payload(
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
            if hide_masked_prompt or (
                scoring_mode == "none" and hint_mode in ("purchase", "wheel")
            ):
                hint_mode = "none"
            custom_words = (
                parse_custom_word_list(payload.custom_words)
                if payload.custom_words is not None
                else list(fallback.custom_words if fallback else [])
            )
            return {
                "name": value("name"),
                "is_public": value("is_public"),
                "max_players": value("max_players"),
                "rounds": value("rounds"),
                "drawing_seconds": value("drawing_seconds"),
                "custom_words": custom_words,
                "custom_words_only": value("custom_words_only"),
                "hint_mode": hint_mode,
                "scoring_mode": scoring_mode,
                "spectators_see_solution": value("spectators_see_solution"),
                "hide_masked_prompt": hide_masked_prompt,
            }

        def validation_error(error: PayloadError) -> dict[str, object]:
            return error.acknowledgement()

        def editable_room_settings(room: Room) -> dict:
            return editable_room_settings_payload(room)
        def schedule_phase_timer(room: Room, seconds: float) -> None:
            async def _runner() -> None:
                task = asyncio.current_task()
                try:
                    await asyncio.sleep(seconds)
                except asyncio.CancelledError:
                    return
                # Deregister ourselves before running the timeout callback. The
                # callback (e.g. _end_round) may itself cancel the phase timer,
                # and without this, that call would cancel *this* still-running
                # task (since we're still registered as the phase owner), which raises
                # CancelledError into us at the next await and prevents the
                # follow-up timer (e.g. for ROUND_END) from ever being scheduled
                # - silently stalling the game.
                assert task is not None
                timer_manager.remove_phase_timer(room.id, task)
                try:
                    await _on_phase_timeout(room)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Unhandled error in phase timeout for room %s", room.id)

            timer_manager.replace_phase_timer(room.id, asyncio.create_task(_runner()))

        def schedule_hint_checkpoints(room: Room) -> None:
            timer_manager.cancel_hint_timers(room.id)
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
                            masked = game.masked_word(
                                p.id,
                                is_spectator=p.is_spectator,
                                spectators_see_solution=room.spectators_see_solution,
                            )
                            await sio.emit(
                                "hint_revealed",
                                {"maskedWord": masked},
                                to=p.sid,
                            )

                timer_manager.add_hint_timer(room.id, asyncio.create_task(_runner()))

        async def _emit_room_state(room: Room) -> None:
            await sio.emit("room_state", room_state_payload(room), room=room.id)

        async def _start_fresh_game(
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
            for player in room.player_list():
                player.score = (
                    0
                    if player.is_spectator
                    else (STARTING_SCORE if room.scoring_mode == "default" else 0)
                )
            room.state = "playing"
            room.game = Game(
                turn_order=[player.id for player in active_players],
                rounds_total=room.rounds,
                word_pool=room.effective_word_pool(),
                drawing_seconds=room.drawing_seconds,
                hint_mode=room.hint_mode,
                scoring_mode=room.scoring_mode,
                hide_masked_prompt=room.hide_masked_prompt,
            )
            await _emit_room_state(room)
            if restarted:
                await sio.emit(
                    "chat_message",
                    {
                        "playerId": "",
                        "nickname": "",
                        "text": "The game was restarted by player vote.",
                        "correct": False,
                        "system": True,
                    },
                    room=room.id,
                )
            await sio.emit("game_started", {"restarted": restarted}, room=room.id)
            await _start_turn(room)

        async def _emit_canvas_sync(room: Room, sid: str) -> None:
            if not room.game:
                return
            await sio.emit(
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
            await sio.emit(
                event,
                payload,
                to=to,
                room=None if to else room.id,
            )

        async def _request_canvas_actions(
            room: Room,
            sid: str,
            expected: int,
            received: int,
        ) -> None:
            await sio.emit(
                "request_canvas_actions",
                [room.game.canvas.generation, expected, received],
                to=sid,
            )

        async def _sync_player_view(sid: str, room: Room, player, *, sync_canvas: bool = True) -> None:
            """Push authoritative game/canvas state to one socket (join or soft resync)."""
            game = room.game
            if not game:
                return
            if game.phase in (Phase.CHOOSING_WORD, Phase.DRAWING):
                await sio.emit(
                    "sync_game",
                    _turn_payload(game, player, room.spectators_see_solution),
                    to=sid,
                )
                if sync_canvas:
                    await _emit_canvas_sync(room, sid)
                if player.id == game.current_drawer:
                    if game.phase == Phase.CHOOSING_WORD:
                        await sio.emit(
                            "your_word_choices",
                            {
                                "choices": game.word_choices,
                                "seconds": round(game.remaining_seconds()),
                            },
                            to=sid,
                        )
                    elif sync_canvas:
                        await sio.emit("you_are_drawing", {"word": game.word}, to=sid)
            elif game.phase == Phase.ROUND_END:
                await sio.emit("round_ended", _round_ended_payload(room), to=sid)

        async def _join_socket_room(sid: str, room: Room, player, is_reconnect: bool) -> None:
            superseded_sid = player.sid if player.sid != sid else None
            player.sid = sid
            player.connected = True
            await sio.save_session(sid, {"room_id": room.id, "player_id": player.id})
            await sio.enter_room(sid, room.id)
            if superseded_sid:
                await sio.disconnect(superseded_sid)
            timer_manager.cancel_disconnect_timer(player.id)
            await _emit_room_state(room)
            event_name = "player_reconnected" if is_reconnect else "player_joined"
            await sio.emit(
                event_name,
                {"playerId": player.id, "nickname": player.nickname},
                room=room.id,
            )
            await _sync_player_view(sid, room, player)

        def _session_ack(room: Room, player: Player) -> dict:
            """Private create/join acknowledgement for the owning socket only."""
            return session_payload(room, player)

        def _turn_payload(game: Game, player: Player | None = None, spectators_see_solution: bool = False) -> dict:
            return turn_payload(game, player, spectators_see_solution)

        async def _start_turn(room: Room) -> None:
            game = room.game
            assert game is not None
            afk_tokens = {p.id for p in room.player_list() if p.is_afk}
            choices = game.start_next_turn(
                afk_tokens,
                canvas_generation=room.allocate_canvas_generation(),
            )
            game.set_phase_deadline(CHOOSE_WORD_SECONDS)
            drawer = room.players.get(game.current_drawer)
            await sio.emit(
                "canvas_reset",
                [
                    game.canvas.revision,
                    game.canvas.generation,
                    game.canvas.sequence,
                    game.canvas.hash,
                ],
                room=room.id,
            )
            await sio.emit(
                "turn_starting",
                {
                    "drawerId": game.current_drawer,
                    "drawerNickname": drawer.nickname if drawer else "",
                    "drawerNameColor": drawer.name_color if drawer else "",
                    "roundNumber": game.round_number,
                    "totalRounds": game.rounds_total,
                    "seconds": CHOOSE_WORD_SECONDS,
                },
                room=room.id,
            )
            if drawer and drawer.sid:
                await sio.emit(
                    "your_word_choices",
                    {"choices": choices, "seconds": CHOOSE_WORD_SECONDS},
                    to=drawer.sid,
                )
            schedule_phase_timer(room, CHOOSE_WORD_SECONDS)

        async def _begin_drawing(room: Room) -> None:
            game = room.game
            assert game is not None
            game.set_phase_deadline(game.drawing_seconds)
            for p in room.player_list():
                if not p.sid:
                    continue
                await sio.emit(
                    "turn_started",
                    {
                        "drawerId": game.current_drawer,
                        "maskedWord": game.masked_word(
                            p.id,
                            is_spectator=p.is_spectator,
                            spectators_see_solution=room.spectators_see_solution,
                        ),
                        "roundNumber": game.round_number,
                        "totalRounds": game.rounds_total,
                        "seconds": game.drawing_seconds,
                        "hintCost": game.hint_cost(p.id),
                        "letterPrices": game.wheel_letter_prices(p.id) if game.hint_mode == "wheel" else None,
                    },
                    to=p.sid,
                )
            schedule_phase_timer(room, game.drawing_seconds)
            schedule_hint_checkpoints(room)

        async def _end_round(room: Room) -> bool:
            game = room.game
            if not game or game.phase != Phase.DRAWING:
                return False
            timer_manager.cancel_phase_timer(room.id)
            timer_manager.cancel_hint_timers(room.id)
            drawer_bonus = game.end_round()
            if drawer_bonus is None:
                return False
            drawer = room.players.get(game.current_drawer)
            if drawer:
                drawer.score += drawer_bonus
            room.last_game_drawings.append(
                DrawingRecapEntry(
                    round_number=game.round_number,
                    turn_number=len(room.last_game_drawings) + 1,
                    drawer_id=game.current_drawer or "",
                    drawer_nickname=drawer.nickname if drawer else "Unknown player",
                    drawer_name_color=drawer.name_color if drawer else None,
                    word=game.word or "",
                    action_count=len(game.canvas.history),
                    canvas_history=game.canvas.sync_payload(),
                )
            )

            await sio.emit(
                "round_ended",
                _round_ended_payload(room, drawer_bonus=drawer_bonus),
                room=room.id,
            )
            schedule_phase_timer(room, ROUND_END_SECONDS)
            return True

        def _round_ended_payload(room: Room, drawer_bonus: int | None = None) -> dict:
            return round_ended_payload(room, drawer_bonus)

        async def _finish_or_next(room: Room) -> None:
            game = room.game
            assert game is not None
            if game.is_finished():
                timer_manager.cancel_restart_timer(room.id)
                room.restart_vote = None
                room.restart_vote_cooldown_until = 0
                room.state = "waiting"
                room.game = None
                room.last_game_scores = [
                    {
                        "playerId": p.id,
                        "nickname": p.nickname,
                        "nameColor": p.name_color,
                        "score": p.score,
                    }
                    for p in sorted(room.player_list(), key=lambda p: -p.score)
                ]
                await sio.emit(
                    "game_ended",
                    {
                        "scores": room.last_game_scores,
                        "drawings": room.drawing_recap_metadata(),
                    },
                    room=room.id,
                )
                await _emit_room_state(room)
            else:
                await _start_turn(room)

        def _privileged_sids(
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

        async def _end_round_if_all_guessed(room: Room) -> None:
            """End the drawing phase early when every eligible guesser has guessed correctly."""
            game = room.game
            if not game or game.phase != Phase.DRAWING:
                return
            guesser_count = len([
                p for p in room.connected_players()
                if p.id != game.current_drawer and not p.is_spectator and not p.is_afk
            ])
            if game.all_guessed(guesser_count):
                await _end_round(room)

        async def _on_phase_timeout(room: Room) -> None:
            game = room.game
            if not game:
                return
            if game.phase == Phase.CHOOSING_WORD:
                game.force_word_choice()
                await _begin_drawing(room)
            elif game.phase == Phase.DRAWING:
                await _end_round(room)
            elif game.phase == Phase.ROUND_END:
                await _finish_or_next(room)

        # ------------------------------------------------------------------
        # Connection lifecycle
        # ------------------------------------------------------------------

        async def _remove_player_from_game(room: Room, token: str) -> None:
            game = room.game
            if not game:
                return
            was_drawer = game.remove_player_from_rotation(token)
            if not game.turn_order:
                timer_manager.cancel_phase_timer(room.id)
                timer_manager.cancel_hint_timers(room.id)
                timer_manager.cancel_restart_timer(room.id)
                room.restart_vote = None
                room.state = "waiting"
                room.game = None
            elif was_drawer:
                timer_manager.cancel_phase_timer(room.id)
                timer_manager.cancel_hint_timers(room.id)
                if game.is_finished():
                    await _finish_or_next(room)
                else:
                    await _start_turn(room)

        async def _existing_player_for_sid(sid: str, room_id: str) -> Player | None:
            """If this socket already has a live session in the target room, return its player.

            Guards against duplicate create/join calls from the same connection (e.g. a
            client re-invoking an effect) spawning a duplicate "ghost" player.
            """
            return await resolve_existing_player_for_sid(ctx, sid, room_id)

        async def require_current_player(sid: str) -> tuple[Room, Player] | None:
            """Resolve an authenticated room member and reject superseded sockets."""
            return await resolve_current_player(ctx, sid)

        self.room_settings_from_payload = room_settings_from_payload
        self.validation_error = validation_error
        self.editable_room_settings = editable_room_settings
        self.schedule_phase_timer = schedule_phase_timer
        self.schedule_hint_checkpoints = schedule_hint_checkpoints
        self._emit_room_state = _emit_room_state
        self._start_fresh_game = _start_fresh_game
        self._emit_canvas_sync = _emit_canvas_sync
        self._emit_canvas_commit = _emit_canvas_commit
        self._request_canvas_actions = _request_canvas_actions
        self._sync_player_view = _sync_player_view
        self._join_socket_room = _join_socket_room
        self._session_ack = _session_ack
        self._turn_payload = _turn_payload
        self._start_turn = _start_turn
        self._begin_drawing = _begin_drawing
        self._end_round = _end_round
        self._round_ended_payload = _round_ended_payload
        self._finish_or_next = _finish_or_next
        self._privileged_sids = _privileged_sids
        self._end_round_if_all_guessed = _end_round_if_all_guessed
        self._on_phase_timeout = _on_phase_timeout
        self._remove_player_from_game = _remove_player_from_game
        self._existing_player_for_sid = _existing_player_for_sid
        self.require_current_player = require_current_player
