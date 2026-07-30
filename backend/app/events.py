"""Socket.IO event handlers: room lifecycle, game turns, drawing, guessing, chat."""
from __future__ import annotations

import asyncio
import logging
import math
import re

import socketio

from app.game import (
    DRAWING_SECONDS,
    CHOOSE_WORD_SECONDS,
    HINT_MODES,
    ROUND_END_SECONDS,
    SCORING_MODES,
    Game,
    Phase,
)
from app.live_drawing import decode_live_drawing, encode_live_drawing
from app.rooms import (
    Player,
    Room,
    RoomFullError,
    RoomManager,
    STARTING_SCORE,
    normalize_name_color,
)
from app.words import parse_custom_word_list

logger = logging.getLogger("sketchy.events")

RECONNECT_GRACE_SECONDS = 30

MAX_POINTS_PER_MOVE = 256
MAX_BRUSH_WIDTH = 64
# Pointer capture keeps reporting movement after the cursor leaves the canvas.
# Those off-canvas points are required to clip the same segment at the canvas
# edge for remote clients. Keep a generous finite bound to reject pathological
# payloads without restricting normal pointer movement across the viewport.
MAX_NORMALIZED_COORDINATE_MAGNITUDE = 8
DRAW_SHAPES = frozenset(("rectangle", "ellipse", "triangle"))
HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_CANVAS_SEQUENCE = 2**31 - 1

# Per-room asyncio task driving the current phase's timeout (choosing/drawing/round-end).
_phase_timers: dict[str, asyncio.Task] = {}
# Per-room list of asyncio tasks that reveal checkpoint hint letters during drawing.
# Kept separate from _phase_timers so canceling one never cancels the other.
_hint_timers: dict[str, list[asyncio.Task]] = {}
# Per-player-token asyncio task that evicts a disconnected player after a grace period.
_disconnect_timers: dict[str, asyncio.Task] = {}


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _draw_number(value, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and low <= number <= high else None


def _draw_point(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    x = _draw_number(
        value.get("x"),
        -MAX_NORMALIZED_COORDINATE_MAGNITUDE,
        MAX_NORMALIZED_COORDINATE_MAGNITUDE,
    )
    y = _draw_number(
        value.get("y"),
        -MAX_NORMALIZED_COORDINATE_MAGNITUDE,
        MAX_NORMALIZED_COORDINATE_MAGNITUDE,
    )
    return {"x": x, "y": y} if x is not None and y is not None else None


def _draw_style(data: dict) -> tuple[str, int] | None:
    color = data.get("color")
    width = _draw_number(data.get("width"), 1, MAX_BRUSH_WIDTH)
    if (
        not isinstance(color, str)
        or not HEX_COLOR_PATTERN.fullmatch(color)
        or width is None
        or not width.is_integer()
    ):
        return None
    return color.lower(), int(width)


def _validated_draw_payload(event_name: str, data) -> dict | None:
    if event_name == "draw_end":
        return {}
    if not isinstance(data, dict):
        return None
    if event_name == "draw_start":
        point = _draw_point(data)
        style = _draw_style(data)
        if not point or not style:
            return None
        color, width = style
        return {**point, "color": color, "width": width}
    if event_name == "draw_move":
        points = data.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS_PER_MOVE:
            return None
        validated_points = []
        for point in points:
            validated_point = _draw_point(point)
            if validated_point is None:
                return None
            validated_points.append(validated_point)
        return {"points": validated_points}
    if event_name == "draw_shape":
        shape = data.get("shape")
        start = _draw_point(data.get("from"))
        end = _draw_point(data.get("to"))
        style = _draw_style(data)
        if not isinstance(shape, str) or shape not in DRAW_SHAPES or not start or not end or not style:
            return None
        color, width = style
        return {"shape": shape, "from": start, "to": end, "color": color, "width": width}
    if event_name == "draw_fill":
        point = _draw_point(data)
        color = data.get("color")
        if (
            not point
            or not 0 <= point["x"] < 1
            or not 0 <= point["y"] < 1
            or not isinstance(color, str)
            or not HEX_COLOR_PATTERN.fullmatch(color)
        ):
            return None
        return {**point, "color": color.lower()}
    return None


def _canvas_sequence(value) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_CANVAS_SEQUENCE
    ):
        return None
    return value


def register_handlers(sio: socketio.AsyncServer, room_manager: RoomManager) -> None:
    def room_settings_from_data(data: dict, *, fallback: Room | None = None) -> dict:
        """Normalize room settings for both creation and host edits."""
        data = data or {}
        max_players = _clamp(int(data.get("maxPlayers", fallback.max_players if fallback else 8) or 8), 2, 12)
        rounds = _clamp(int(data.get("rounds", fallback.rounds if fallback else 3) or 3), 1, 10)
        drawing_seconds = _clamp(int(data.get("drawingSeconds", fallback.drawing_seconds if fallback else DRAWING_SECONDS) or DRAWING_SECONDS), 15, 240)
        hint_mode = str(data.get("hintMode", fallback.hint_mode if fallback else "none") or "none")
        scoring_mode = str(data.get("scoringMode", fallback.scoring_mode if fallback else "default") or "default")
        if hint_mode not in HINT_MODES:
            hint_mode = "none"
        if scoring_mode not in SCORING_MODES:
            scoring_mode = "default"
        if scoring_mode == "none" and hint_mode in ("purchase", "wheel"):
            hint_mode = "none"
        hide_masked_prompt = bool(data.get("hideMaskedPrompt", fallback.hide_masked_prompt if fallback else False))
        if hide_masked_prompt:
            hint_mode = "none"
        return {
            "name": str(data.get("name", fallback.name if fallback else "") or "").strip()[:40],
            "is_public": bool(data.get("isPublic", fallback.is_public if fallback else True)),
            "max_players": max_players,
            "rounds": rounds,
            "drawing_seconds": drawing_seconds,
            "custom_words": parse_custom_word_list(str(data.get("customWords", "") or "")) if "customWords" in data else list(fallback.custom_words if fallback else []),
            "custom_words_only": bool(data.get("customWordsOnly", fallback.custom_words_only if fallback else False)),
            "hint_mode": hint_mode,
            "scoring_mode": scoring_mode,
            "spectators_see_solution": bool(data.get("spectatorsSeeSolution", fallback.spectators_see_solution if fallback else False)),
            "hide_masked_prompt": hide_masked_prompt,
        }

    def editable_room_settings(room: Room) -> dict:
        return {
            "name": room.name, "isPublic": room.is_public, "maxPlayers": room.max_players,
            "rounds": room.rounds, "drawingSeconds": room.drawing_seconds,
            "customWords": "\n".join(room.custom_words), "customWordsOnly": room.custom_words_only,
            "hintMode": room.hint_mode, "scoringMode": room.scoring_mode,
            "spectatorsSeeSolution": room.spectators_see_solution,
            "hideMaskedPrompt": room.hide_masked_prompt,
        }
    def cancel_phase_timer(room_id: str) -> None:
        task = _phase_timers.pop(room_id, None)
        if task and not task.done():
            task.cancel()
    def schedule_phase_timer(room: Room, seconds: float) -> None:
        cancel_phase_timer(room.id)

        async def _runner() -> None:
            task = asyncio.current_task()
            try:
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                return
            # Deregister ourselves before running the timeout callback. The
            # callback (e.g. _end_round) may itself call cancel_phase_timer,
            # and without this, that call would cancel *this* still-running
            # task (since we're still stored in _phase_timers), which raises
            # CancelledError into us at the next await and prevents the
            # follow-up timer (e.g. for ROUND_END) from ever being scheduled
            # - silently stalling the game.
            if _phase_timers.get(room.id) is task:
                del _phase_timers[room.id]
            try:
                await _on_phase_timeout(room)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Unhandled error in phase timeout for room %s", room.id)

        _phase_timers[room.id] = asyncio.create_task(_runner())

    def cancel_hint_timers(room_id: str) -> None:
        tasks = _hint_timers.pop(room_id, [])
        for task in tasks:
            if not task.done():
                task.cancel()

    def schedule_hint_checkpoints(room: Room) -> None:
        cancel_hint_timers(room.id)
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
                            p.token,
                            is_spectator=p.is_spectator,
                            spectators_see_solution=room.spectators_see_solution,
                        )
                        await sio.emit(
                            "hint_revealed",
                            {"maskedWord": masked},
                            to=p.sid,
                        )

            _hint_timers.setdefault(room.id, []).append(asyncio.create_task(_runner()))

    def cancel_disconnect_timer(token: str) -> None:
        task = _disconnect_timers.pop(token, None)
        if task and not task.done():
            task.cancel()

    async def _emit_room_state(room: Room) -> None:
        await sio.emit("room_state", room.to_state_payload(), room=room.id)

    async def _emit_canvas_sync(room: Room, sid: str) -> None:
        if not room.game:
            return
        await sio.emit(
            "sync_strokes",
            (
                room.game.canvas_sync_payload(),
                room.game.canvas_revision,
                room.game.canvas_sequence,
                room.game.canvas_hash,
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
        commit = room.game.canvas_commit(sequence)
        if not commit:
            return
        revision, history_hash, mutation = commit
        event = "canvas_undo" if mutation == "undo" else "canvas_commit"
        payload = (
            [sequence, revision - 1, revision, history_hash]
            if mutation == "undo"
            else [sequence, revision, history_hash]
        )
        await sio.emit(
            event,
            payload,
            to=to,
            room=None if to else room.id,
        )

    async def _request_canvas_actions(
        sid: str,
        expected: int,
        received: int,
    ) -> None:
        await sio.emit(
            "request_canvas_actions",
            [expected, received],
            to=sid,
        )

    async def _join_socket_room(sid: str, room: Room, player, is_reconnect: bool) -> None:
        player.sid = sid
        player.connected = True
        await sio.save_session(sid, {"room_id": room.id, "token": player.token})
        await sio.enter_room(sid, room.id)
        cancel_disconnect_timer(player.token)
        await _emit_room_state(room)
        event_name = "player_reconnected" if is_reconnect else "player_joined"
        await sio.emit(
            event_name,
            {"token": player.token, "nickname": player.nickname},
            room=room.id,
        )
        if room.game and room.game.phase in (Phase.CHOOSING_WORD, Phase.DRAWING):
            await sio.emit(
                "sync_game",
                _turn_payload(room.game, player, room.spectators_see_solution),
                to=sid,
            )
            await _emit_canvas_sync(room, sid)
            if player.token == room.game.current_drawer:
                if room.game.phase == Phase.CHOOSING_WORD:
                    await sio.emit(
                        "your_word_choices",
                        {
                            "choices": room.game.word_choices,
                            "seconds": round(room.game.remaining_seconds()),
                        },
                        to=sid,
                    )
                else:
                    await sio.emit("you_are_drawing", {"word": room.game.word}, to=sid)

    def _turn_payload(game: Game, player: Player | None = None, spectators_see_solution: bool = False) -> dict:
        token = player.token if player else None
        is_spec = player.is_spectator if player else False
        return {
            "phase": game.phase.value,
            "drawerToken": game.current_drawer,
            "maskedWord": game.masked_word(
                token,
                is_spectator=is_spec,
                spectators_see_solution=spectators_see_solution,
            ),
            "roundNumber": game.round_number,
            "totalRounds": game.rounds_total,
            "remainingSeconds": round(game.remaining_seconds()),
            "hintCost": game.hint_cost(token) if token else None,
            "letterPrices": game.wheel_letter_prices(token) if token and game.hint_mode == "wheel" else None,
        }

    async def _start_turn(room: Room) -> None:
        game = room.game
        assert game is not None
        afk_tokens = {p.token for p in room.player_list() if p.is_afk}
        choices = game.start_next_turn(afk_tokens)
        game.set_phase_deadline(CHOOSE_WORD_SECONDS)
        drawer = room.players.get(game.current_drawer)
        await sio.emit(
            "canvas_reset",
            [game.canvas_revision, game.canvas_sequence, game.canvas_hash],
            room=room.id,
        )
        await sio.emit(
            "turn_starting",
            {
                "drawerToken": game.current_drawer,
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
        schedule_hint_checkpoints(room)
        for p in room.player_list():
            if not p.sid:
                continue
            await sio.emit(
                "turn_started",
                {
                    "drawerToken": game.current_drawer,
                    "maskedWord": game.masked_word(
                        p.token,
                        is_spectator=p.is_spectator,
                        spectators_see_solution=room.spectators_see_solution,
                    ),
                    "roundNumber": game.round_number,
                    "totalRounds": game.rounds_total,
                    "seconds": game.drawing_seconds,
                    "hintCost": game.hint_cost(p.token),
                    "letterPrices": game.wheel_letter_prices(p.token) if game.hint_mode == "wheel" else None,
                },
                to=p.sid,
            )
        schedule_phase_timer(room, game.drawing_seconds)
        schedule_hint_checkpoints(room)

    async def _end_round(room: Room) -> bool:
        game = room.game
        if not game or game.phase != Phase.DRAWING:
            return False
        cancel_phase_timer(room.id)
        cancel_hint_timers(room.id)
        drawer_bonus = game.end_round()
        if drawer_bonus is None:
            return False
        drawer = room.players.get(game.current_drawer)
        if drawer:
            drawer.score += drawer_bonus

        # Build a per-player score breakdown for this round: how many points
        # each player just earned (guess points, or the drawer's bonus), plus
        # their leaderboard rank before/after those points were applied, so
        # the client can show a "you moved up 2 places" style overtake.
        players = room.player_list()
        deltas = {
            p.token: game.guess_points.get(p.token, 0)
            + (drawer_bonus if p.token == game.current_drawer else 0)
            for p in players
        }
        previous_scores = {p.token: p.score - deltas[p.token] for p in players}
        previous_ranks = {
            p.token: rank
            for rank, p in enumerate(sorted(players, key=lambda p: -previous_scores[p.token]), start=1)
        }
        new_ranked = sorted(players, key=lambda p: -p.score)
        new_ranks = {p.token: rank for rank, p in enumerate(new_ranked, start=1)}

        await sio.emit(
            "round_ended",
            {
                "word": game.word,
                "drawerToken": game.current_drawer,
                "drawerBonus": drawer_bonus,
                "seconds": ROUND_END_SECONDS,
                "guesses": [
                    {
                        "token": p.token,
                        "nickname": p.nickname,
                        "nameColor": p.name_color,
                        "seconds": game.guess_times[p.token],
                    }
                    for p in sorted(
                        players,
                        key=lambda player: game.guess_times.get(player.token, float("inf")),
                    )
                    if p.token in game.guess_times
                ],
                "scores": [
                    {
                        "token": p.token,
                        "nickname": p.nickname,
                        "nameColor": p.name_color,
                        "score": p.score,
                        "delta": deltas[p.token],
                        "previousRank": previous_ranks[p.token],
                        "newRank": new_ranks[p.token],
                    }
                    for p in new_ranked
                ],
            },
            room=room.id,
        )
        schedule_phase_timer(room, ROUND_END_SECONDS)
        return True

    async def _finish_or_next(room: Room) -> None:
        game = room.game
        assert game is not None
        if game.is_finished():
            room.state = "waiting"
            room.game = None
            room.last_game_scores = [
                {
                    "token": p.token,
                    "nickname": p.nickname,
                    "nameColor": p.name_color,
                    "score": p.score,
                }
                for p in sorted(room.player_list(), key=lambda p: -p.score)
            ]
            await sio.emit(
                "game_ended",
                {"scores": room.last_game_scores},
                room=room.id,
            )
            await _emit_room_state(room)
        else:
            await _start_turn(room)

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

    @sio.event
    async def connect(sid, environ, auth):
        logger.info("socket connected: %s", sid)

    @sio.event
    async def disconnect(sid):
        session = await sio.get_session(sid) if sid else None
        if not session:
            return
        room = room_manager.get_room(session.get("room_id"))
        token = session.get("token")
        if not room or not token or token not in room.players:
            return
        player = room.players[token]
        if player.sid != sid:
            # Stale disconnect for a sid that's already been superseded by a
            # newer connection (e.g. the client reconnected - a new sid ran
            # join_room and updated player.sid - before this older sid's
            # disconnect event was processed). The player is still actively
            # connected via the newer sid, so ignore this one rather than
            # incorrectly marking them disconnected.
            return
        player.connected = False
        player.sid = None
        for p in room.players.values():
            p.kick_votes.discard(token)
            p.afk_votes.discard(token)
        await sio.emit(
            "player_disconnected", {"token": token, "nickname": player.nickname}, room=room.id
        )
        await _emit_room_state(room)

        async def _evict_after_grace() -> None:
            try:
                await asyncio.sleep(RECONNECT_GRACE_SECONDS)
            except asyncio.CancelledError:
                return
            still_present = room.players.get(token)
            if not still_present or still_present.connected:
                return
            room_manager.remove_player(room, token)
            await sio.emit("player_left", {"token": token}, room=room.id)
            if not room.connected_players():
                cancel_phase_timer(room.id)
                cancel_hint_timers(room.id)
                room_manager.remove_room_if_empty(room.id)
                return
            await _remove_player_from_game(room, token)
            await _emit_room_state(room)

        _disconnect_timers[token] = asyncio.create_task(_evict_after_grace())

    # ------------------------------------------------------------------
    # Room lifecycle
    # ------------------------------------------------------------------

    async def _remove_player_from_game(room: Room, token: str) -> None:
        game = room.game
        if not game:
            return
        was_drawer = game.remove_player_from_rotation(token)
        if not game.turn_order:
            cancel_phase_timer(room.id)
            cancel_hint_timers(room.id)
            room.state = "waiting"
            room.game = None
        elif was_drawer:
            cancel_phase_timer(room.id)
            cancel_hint_timers(room.id)
            if game.is_finished():
                await _finish_or_next(room)
            else:
                await _start_turn(room)

    async def _existing_player_for_sid(sid: str, room_id: str) -> Player | None:
        """If this socket already has a live session in the target room, return its player.

        Guards against duplicate create/join calls from the same connection (e.g. a
        client re-invoking an effect) spawning a duplicate "ghost" player.
        """
        session = await sio.get_session(sid)
        if not session or session.get("room_id") != room_id:
            return None
        existing_room = room_manager.get_room(room_id)
        if not existing_room:
            return None
        return existing_room.players.get(session.get("token"))

    @sio.event
    async def create_room(sid, data):
        data = data or {}
        nickname = str(data.get("nickname", "")).strip()[:20] or "Player"
        settings = room_settings_from_data(data)

        room = room_manager.create_room(
            **settings,
        )
        player = room_manager.add_player(
            room,
            nickname,
            name_color=normalize_name_color(data.get("nameColor")),
        )
        await _join_socket_room(sid, room, player, is_reconnect=False)
        return {"ok": True, "roomId": room.id, "code": room.code, "token": player.token}

    @sio.event
    async def get_room_settings(sid, data=None):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        player = room.players.get(session.get("token")) if room and session else None
        if not room or not player or not player.is_host:
            return {"ok": False, "error": "Only the host can view room settings"}
        return {"ok": True, "settings": editable_room_settings(room)}

    @sio.event
    async def get_custom_words(sid, data=None):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        player = room.players.get(session.get("token")) if room and session else None
        if not room or not player:
            return {"ok": False, "error": "Not in this room"}
        if player.is_spectator:
            return {"ok": False, "error": "Only players can view custom words"}
        if room.state != "waiting" or room.game:
            return {
                "ok": False,
                "error": "Custom words can only be viewed in the waiting room",
            }
        return {"ok": True, "words": list(room.custom_words)}

    @sio.event
    async def update_room_settings(sid, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        player = room.players.get(session.get("token")) if room and session else None
        if not room or not player or not player.is_host:
            return {"ok": False, "error": "Only the host can change room settings"}
        if room.state != "waiting" or room.game:
            return {"ok": False, "error": "Settings can only be changed in the waiting room"}
        settings = room_settings_from_data(data or {}, fallback=room)
        active_count = len([p for p in room.player_list() if not p.is_spectator])
        if settings["max_players"] < active_count:
            return {"ok": False, "error": f"Max players cannot be below the {active_count} players already in the room"}
        if not settings["custom_words"]:
            settings["custom_words_only"] = False
        for key, value in settings.items():
            setattr(room, key, value)
        await sio.emit("chat_message", {"token": "", "nickname": "", "text": "The host updated the room settings.", "correct": False, "system": True}, room=room.id)
        await _emit_room_state(room)
        return {"ok": True}

    @sio.event
    async def get_room_preview(sid, data):
        """Return invite-screen metadata without joining or exposing player details."""
        room = room_manager.get_room_by_code((data or {}).get("code"))
        if not room:
            return {"ok": False, "error": "Room not found"}
        return {"ok": True, "room": room.to_public_summary()}

    @sio.event
    async def join_room(sid, data):
        data = data or {}
        token = data.get("token")
        room_id = data.get("roomId")
        code = data.get("code")
        nickname = str(data.get("nickname", "")).strip()[:20] or "Player"
        name_color = normalize_name_color(data.get("nameColor"))
        as_spectator = bool(data.get("asSpectator", False))

        room = room_manager.get_room(room_id) or room_manager.get_room_by_code(code)
        if not room:
            return {"ok": False, "error": "Room not found"}

        # Checked before the token-reconnect branch below: a client's first
        # join_room call (e.g. from the lobby) is very often followed by a
        # second one moments later on the very same socket (e.g. GameRoomPage
        # re-joining with the token it was just given). That second call
        # would otherwise match the token-reconnect branch and fire a
        # spurious "reconnected" message for a session that never actually
        # disconnected - so if this exact socket already has a live session
        # in this room, just confirm it rather than reprocessing the join.
        already_joined = await _existing_player_for_sid(sid, room.id)
        if already_joined:
            return {"ok": True, "roomId": room.id, "code": room.code, "token": already_joined.token}

        if token and token in room.players:
            player = room.players[token]
            if name_color:
                player.name_color = name_color
            await _join_socket_room(sid, room, player, is_reconnect=True)
            return {"ok": True, "roomId": room.id, "code": room.code, "token": player.token}
        if token:
            return {"ok": False, "error": "Your previous room session has expired", "invalidToken": True}

        try:
            player = room_manager.add_player(
                room,
                nickname,
                is_spectator=as_spectator,
                name_color=name_color,
            )
        except RoomFullError:
            return {"ok": False, "error": "Room is full"}

        # A game already in progress keeps running its existing turn_order -
        # joining mid-game just enrolls the new player into future turns
        # (appended to the end, so everyone already playing keeps their
        # relative order) rather than blocking the join entirely.
        if room.game and not player.is_spectator:
            room.game.add_player_to_rotation(player.token)

        await _join_socket_room(sid, room, player, is_reconnect=False)
        return {"ok": True, "roomId": room.id, "code": room.code, "token": player.token}

    @sio.event
    async def update_player_settings(sid, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        player = room.players.get(session.get("token")) if room and session else None
        if not room or not player:
            return {"ok": False, "error": "Not in this room"}
        name_color = normalize_name_color((data or {}).get("nameColor"))
        if not name_color:
            return {"ok": False, "error": "Invalid player name color"}
        player.name_color = name_color
        await _emit_room_state(room)
        return {"ok": True}

    @sio.event
    async def become_player(sid, data=None):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        player = room.players.get(session.get("token")) if room and session else None
        if not room or not player:
            return {"ok": False, "error": "Not in this room"}
        if room.state != "waiting" or room.game:
            return {"ok": False, "error": "You can only join as a player from the waiting room"}
        if not player.is_spectator:
            return {"ok": False, "error": "You are already a player"}

        active_count = len([candidate for candidate in room.players.values() if not candidate.is_spectator])
        if active_count >= room.max_players:
            return {"ok": False, "error": "Player slots are full"}

        player.is_spectator = False
        player.score = STARTING_SCORE if room.scoring_mode == "default" else 0
        await sio.emit(
            "chat_message",
            {
                "token": "",
                "nickname": "",
                "text": f"{player.nickname} joined as a player.",
                "correct": False,
                "system": True,
            },
            room=room.id,
        )
        await _emit_room_state(room)
        return {"ok": True}

    @sio.event
    async def leave_room(sid, data=None):
        session = await sio.get_session(sid)
        if not session:
            return
        room = room_manager.get_room(session.get("room_id"))
        token = session.get("token")
        if not room or not token:
            return
        cancel_disconnect_timer(token)
        room_manager.remove_player(room, token)
        await sio.leave_room(sid, room.id)
        await sio.save_session(sid, {})
        if not room.connected_players():
            cancel_phase_timer(room.id)
            cancel_hint_timers(room.id)
            room_manager.remove_room_if_empty(room.id)
        else:
            await _remove_player_from_game(room, token)
            await sio.emit("player_left", {"token": token}, room=room.id)
            await _emit_room_state(room)

    @sio.event
    async def toggle_afk(sid, data=None):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room:
            return {"ok": False, "error": "Not in a room"}
        player = room.players.get(session.get("token"))
        if not player:
            return {"ok": False, "error": "Not in this room"}

        target_afk = not player.is_afk
        if data and "afk" in data:
            target_afk = bool(data["afk"])

        player.is_afk = target_afk
        await _emit_room_state(room)

        if room.game and room.state == "playing":
            if player.is_afk and player.token == room.game.current_drawer:
                if room.game.phase == Phase.CHOOSING_WORD:
                    await _start_turn(room)
                elif room.game.phase == Phase.DRAWING:
                    await _end_round(room)
            elif room.game.phase == Phase.DRAWING:
                guesser_count = len([
                    p for p in room.connected_players()
                    if p.token != room.game.current_drawer and not p.is_spectator and not p.is_afk
                ])
                if room.game.all_guessed(guesser_count):
                    await _end_round(room)

        return {"ok": True, "isAfk": player.is_afk}

    @sio.event
    async def vote_player(sid, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room:
            return {"ok": False, "error": "Not in a room"}
        voter = room.players.get(session.get("token"))
        if not voter:
            return {"ok": False, "error": "Not in this room"}

        target_token = (data or {}).get("targetToken")
        action = (data or {}).get("action")
        if not target_token or action not in ("kick", "afk"):
            return {"ok": False, "error": "Invalid vote parameter"}

        target = room.players.get(target_token)
        if not target or target.token == voter.token:
            return {"ok": False, "error": "Cannot vote on yourself or non-existent player"}

        target.kick_votes = {v for v in target.kick_votes if v in room.players and room.players[v].connected}
        target.afk_votes = {v for v in target.afk_votes if v in room.players and room.players[v].connected}
        connected_players = room.connected_players()
        required_votes = (len(connected_players) // 2) + 1

        if action == "kick":
            if voter.token in target.kick_votes:
                target.kick_votes.remove(voter.token)
            else:
                target.kick_votes.add(voter.token)

            if len(target.kick_votes) >= required_votes:
                target_sid = target.sid
                room_manager.remove_player(room, target.token)
                if target_sid:
                    await sio.emit("kicked", {"reason": "You were kicked from the room by vote."}, to=target_sid)
                    await sio.leave_room(target_sid, room.id)
                await sio.emit(
                    "chat_message",
                    {"token": "", "nickname": "", "text": f"{target.nickname} was kicked by vote.", "correct": False, "system": True},
                    room=room.id,
                )
                if room.game and room.state == "playing":
                    await _remove_player_from_game(room, target.token)
                await _emit_room_state(room)
                return {"ok": True, "action": "kick", "executed": True}

        elif action == "afk":
            if voter.token in target.afk_votes:
                target.afk_votes.remove(voter.token)
            else:
                target.afk_votes.add(voter.token)

            if len(target.afk_votes) >= required_votes:
                target.is_afk = True
                target.afk_votes.clear()
                if target.sid:
                    await sio.emit("voted_afk", {"message": "You were marked AFK by room vote."}, to=target.sid)
                await sio.emit(
                    "chat_message",
                    {"token": "", "nickname": "", "text": f"{target.nickname} was marked AFK by vote.", "correct": False, "system": True},
                    room=room.id,
                )
                if room.game and room.state == "playing":
                    if target.token == room.game.current_drawer:
                        if room.game.phase == Phase.CHOOSING_WORD:
                            await _start_turn(room)
                        elif room.game.phase == Phase.DRAWING:
                            await _end_round(room)
                    elif room.game.phase == Phase.DRAWING:
                        guesser_count = len([
                            p for p in room.connected_players()
                            if p.token != room.game.current_drawer and not p.is_spectator and not p.is_afk
                        ])
                        if room.game.all_guessed(guesser_count):
                            await _end_round(room)
                await _emit_room_state(room)
                return {"ok": True, "action": "afk", "executed": True}

        await _emit_room_state(room)
        return {"ok": True, "action": action, "executed": False}

    # ------------------------------------------------------------------
    # Game flow
    # ------------------------------------------------------------------

    @sio.event
    async def start_game(sid, data=None):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room:
            return {"ok": False, "error": "Not in a room"}
        player = room.players.get(session.get("token"))
        if not player or not player.is_host:
            return {"ok": False, "error": "Only the host can start the game"}
        active_players = [p for p in room.connected_players() if not p.is_spectator and not p.is_afk]
        if len(active_players) < 2:
            return {"ok": False, "error": "Need at least 2 active non-AFK players to start"}
        if room.state == "playing":
            return {"ok": False, "error": "Game already in progress"}

        room.last_game_scores = []
        for p in room.player_list():
            p.score = 0 if p.is_spectator else (STARTING_SCORE if room.scoring_mode == "default" else 0)
        room.state = "playing"
        room.game = Game(
            turn_order=[p.token for p in active_players],
            rounds_total=room.rounds,
            word_pool=room.effective_word_pool(),
            drawing_seconds=room.drawing_seconds,
            hint_mode=room.hint_mode,
            scoring_mode=room.scoring_mode,
            hide_masked_prompt=room.hide_masked_prompt,
        )
        await _emit_room_state(room)
        await sio.emit("game_started", {}, room=room.id)
        await _start_turn(room)
        return {"ok": True}

    @sio.event
    async def select_word(sid, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return {"ok": False, "error": "Game is not ready for word selection"}
        token = session.get("token")
        word = str((data or {}).get("word", ""))
        if not room.game.choose_word(token, word):
            return {"ok": False, "error": "That word is no longer available"}
        cancel_phase_timer(room.id)
        await _begin_drawing(room)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    @sio.event
    async def draw(sid, data, sequence_data=None):
        try:
            packet = decode_live_drawing(data)
        except ValueError:
            return
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return
        token = session.get("token")
        if token != room.game.current_drawer or room.game.phase != Phase.DRAWING:
            return
        starts_action = packet.event in {
            "draw_start",
            "draw_shape",
            "draw_fill",
            "clear_canvas",
        }
        sequence = _canvas_sequence(sequence_data) if starts_action else None
        if starts_action:
            if sequence is None:
                return
            if room.game.active_draw_sequence is not None:
                if (
                    packet.event == "draw_start"
                    and sequence == room.game.active_draw_sequence
                ):
                    room.game.restart_active_path()
                else:
                    expected_sequence = room.game.canvas_sequence + 1
                    await _request_canvas_actions(
                        sid,
                        expected_sequence,
                        sequence,
                    )
                    return
            if sequence <= room.game.canvas_sequence:
                if packet.event == "draw_start":
                    room.game.discarding_draw_sequence = True
                await _emit_canvas_commit(room, sequence, to=sid)
                return
            expected_sequence = room.game.canvas_sequence + 1
            if sequence != expected_sequence:
                if packet.event == "draw_start":
                    room.game.discarding_draw_sequence = True
                await _request_canvas_actions(
                    sid,
                    expected_sequence,
                    sequence,
                )
                return
        elif room.game.discarding_draw_sequence:
            if packet.event == "draw_end":
                room.game.discarding_draw_sequence = False
            return
        if packet.event == "clear_canvas":
            if not room.game.clear_canvas_stroke():
                return
            await sio.emit(
                "draw",
                data if isinstance(data, int) else bytes(data),
                room=room.id,
                skip_sid=sid,
            )
            room.game.commit_canvas_sequence(sequence)
            await _emit_canvas_commit(room, sequence)
            return
        payload = _validated_draw_payload(packet.event, packet.payload)
        if payload is None:
            return
        if not room.game.record_stroke(packet.event, payload):
            return
        if packet.event == "draw_start":
            room.game.discarding_draw_sequence = False
            room.game.active_draw_sequence = sequence
        await sio.emit(
            "draw",
            data if isinstance(data, int) else bytes(data),
            room=room.id,
            skip_sid=sid,
        )
        if packet.event == "draw_end":
            active_sequence = room.game.active_draw_sequence
            if active_sequence is None:
                return
            room.game.active_draw_sequence = None
            room.game.commit_canvas_sequence(active_sequence)
            await _emit_canvas_commit(room, active_sequence)
        elif packet.event in {"draw_shape", "draw_fill"}:
            room.game.commit_canvas_sequence(sequence)
            await _emit_canvas_commit(room, sequence)

    @sio.event
    async def undo_stroke(sid, data=None):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return
        token = session.get("token")
        if token != room.game.current_drawer:
            return {"ok": False, "error": "Only the drawer can undo"}
        if (
            not isinstance(data, list)
            or len(data) != 3
            or (sequence := _canvas_sequence(data[0])) is None
            or isinstance(data[1], bool)
            or not isinstance(data[1], int)
            or data[1] < 0
            or isinstance(data[2], bool)
            or not isinstance(data[2], int)
            or not 0 <= data[2] <= 0xFFFFFFFF
        ):
            return {"ok": False, "error": "Invalid Undo request"}
        if sequence <= room.game.canvas_sequence:
            commit = room.game.canvas_commit(sequence)
            if commit and commit[2] == "undo":
                await _emit_canvas_commit(room, sequence, to=sid)
                return {"ok": True}
            return {"ok": False, "error": "Sequence already committed"}
        expected_sequence = room.game.canvas_sequence + 1
        if sequence != expected_sequence:
            await _request_canvas_actions(sid, expected_sequence, sequence)
            return {"ok": False, "error": "Drawing actions are out of sequence"}
        if data[1] != room.game.canvas_revision or data[2] != room.game.canvas_hash:
            await _emit_canvas_sync(room, sid)
            return {"ok": False, "error": "Canvas history is out of sync"}
        if room.game.undo_last_stroke():
            room.game.commit_canvas_sequence(sequence, "undo")
            await _emit_canvas_commit(room, sequence)
            return {"ok": True}
        return {"ok": False, "error": "Nothing to undo"}

    # ------------------------------------------------------------------
    # Guessing / chat
    # ------------------------------------------------------------------

    @sio.event
    async def send_chat(sid, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        player = room.players.get(session.get("token")) if room and session else None
        if not room or not player:
            return {"ok": False, "error": "Not in a room"}
        if room.state != "waiting":
            return {"ok": False, "error": "Waiting-room chat is unavailable during a game"}
        text = str((data or {}).get("text", "")).strip()[:60]
        if not text:
            return {"ok": False, "error": "Message cannot be empty"}
        if player.is_afk and not player.is_spectator:
            player.is_afk = False
            await _emit_room_state(room)
        await sio.emit(
            "chat_message",
            {"token": player.token, "nickname": player.nickname, "text": text, "correct": False, "isSpectator": player.is_spectator},
            room=room.id,
        )
        return {"ok": True}

    @sio.event
    async def guess(sid, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return
        player = room.players.get(session.get("token"))
        if not player:
            return
        text = str((data or {}).get("text", "")).strip()
        if not text:
            return

        if player.is_afk:
            player.is_afk = False
            await _emit_room_state(room)

        game = room.game

        # Once a player has already found the word this round, anything else
        # they type could spoil it for players who haven't guessed yet (or
        # just be confusing out-of-context chatter). Keep the rest of their
        # messages for the round visible only to the drawer and other
        # players who've also already guessed correctly, flagged so the
        # client can render a clear "restricted visibility" indicator.
        # Spectators and players who have already guessed correctly can chat,
        # but their messages are restricted to the drawer, other correct guessers, and spectators.
        if player.is_spectator:
            in_the_know = [
                p.sid
                for p in room.player_list()
                if p.sid and (p.token in game.correct_guessers or p.token == game.current_drawer or p.is_spectator)
            ]
            for target_sid in in_the_know:
                await sio.emit(
                    "chat_message",
                    {
                        "token": player.token,
                        "nickname": player.nickname,
                        "text": text,
                        "correct": False,
                        "restricted": True,
                        "isSpectator": True,
                    },
                    to=target_sid,
                )
            return

        if player.token in game.correct_guessers:
            in_the_know = [
                p.sid
                for p in room.player_list()
                if p.sid and (p.token in game.correct_guessers or p.token == game.current_drawer or p.is_spectator)
            ]
            for target_sid in in_the_know:
                await sio.emit(
                    "chat_message",
                    {
                        "token": player.token,
                        "nickname": player.nickname,
                        "text": text,
                        "correct": False,
                        "restricted": True,
                    },
                    to=target_sid,
                )
            return

        correct, points = game.submit_guess(player.token, text)
        if not correct:
            hint = game.guess_hint(player.token, text)
            if hint:
                hint_text = f'"{text}" is very close!' if hint == "close" else "Some words are correct"
                # The guesser should always see their own guess, even when it's
                # not broadcast to the rest of the room.
                await sio.emit(
                    "chat_message",
                    {"token": player.token, "nickname": player.nickname, "text": text, "correct": False},
                    to=sid,
                )
                await sio.emit(
                    "chat_message",
                    {
                        "token": player.token,
                        "nickname": player.nickname,
                        "text": hint_text,
                        "correct": False,
                        "close": True,
                    },
                    to=sid,
                )
                in_the_know = [
                    p.sid
                    for p in room.player_list()
                    if p.sid
                    and p.sid != sid
                    and (p.token in game.correct_guessers or p.token == game.current_drawer or p.is_spectator)
                ]
                for target_sid in in_the_know:
                    await sio.emit(
                        "chat_message",
                        {"token": player.token, "nickname": player.nickname, "text": text, "correct": False},
                        to=target_sid,
                    )
            else:
                await sio.emit(
                    "chat_message",
                    {"token": player.token, "nickname": player.nickname, "text": text, "correct": False},
                    room=room.id,
                )
            return

        player.score += points
        await sio.emit(
            "correct_guess",
            {"token": player.token, "nickname": player.nickname, "points": points},
            room=room.id,
        )
        await sio.emit("you_guessed_correctly", {"word": game.word}, to=player.sid)
        in_the_know = [
            p.sid
            for p in room.player_list()
            if p.sid and (p.token in game.correct_guessers or p.token == game.current_drawer or p.is_spectator)
        ]
        for target_sid in in_the_know:
            await sio.emit(
                "chat_message",
                {"token": player.token, "nickname": player.nickname, "text": text, "correct": True},
                to=target_sid,
            )

        guesser_count = len([p for p in room.connected_players() if p.token != game.current_drawer and not p.is_spectator])
        if game.all_guessed(guesser_count):
            await _end_round(room)

    @sio.event
    async def buy_hint(sid, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return {"ok": False, "error": "Not in an active game"}
        game = room.game
        if game.hint_mode != "purchase":
            return {"ok": False, "error": "Hint purchasing is disabled in this room"}
        player = room.players.get(session.get("token"))
        if not player:
            return {"ok": False, "error": "Not in this room"}
        try:
            slot = int((data or {}).get("slot"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid hint"}
        cost = game.hint_cost(player.token)
        if player.score < cost:
            return {"ok": False, "error": "Not enough points"}
        if not game.buy_hint_letter(player.token, slot):
            return {"ok": False, "error": "Hint unavailable"}

        player.score -= cost
        await sio.emit(
            "hint_revealed",
            {"maskedWord": game.masked_word(player.token), "hintCost": game.hint_cost(player.token)},
            to=sid,
        )
        await _emit_room_state(room)
        return {"ok": True, "cost": cost}

    @sio.event
    async def buy_wheel_letter(sid, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return {"ok": False, "error": "Not in an active game"}
        game = room.game
        if game.hint_mode != "wheel":
            return {"ok": False, "error": "Letter buying is disabled in this room"}
        player = room.players.get(session.get("token"))
        if not player:
            return {"ok": False, "error": "Not in this room"}
        letter = str((data or {}).get("letter", "")).strip().lower()
        if len(letter) != 1 or not letter.isalpha():
            return {"ok": False, "error": "Invalid letter"}
        cost = game.wheel_hint_cost(player.token, letter)
        if player.score < cost:
            return {"ok": False, "error": "Not enough points"}
        if not game.buy_wheel_letter(player.token, letter):
            return {"ok": False, "error": "Letter unavailable"}

        player.score -= cost
        found_count = sum(1 for i in game.letter_positions if game.word[i].lower() == letter)
        await sio.emit(
            "hint_revealed",
            {
                "maskedWord": game.masked_word(player.token),
                "letterPrices": game.wheel_letter_prices(player.token),
            },
            to=sid,
        )
        if found_count:
            feedback = f"You bought '{letter.upper()}' for {cost} pts - found {found_count} time{'s' if found_count != 1 else ''}!"
        else:
            feedback = f"You bought '{letter.upper()}' for {cost} pts - not in the word."
        await sio.emit(
            "chat_message",
            {"token": "", "nickname": "", "text": feedback, "correct": False, "system": True},
            to=sid,
        )
        await _emit_room_state(room)
        return {"ok": True, "cost": cost, "found": found_count}

    @sio.event
    async def request_sync_strokes(sid):
        session = await sio.get_session(sid) if sid else None
        if not session:
            return
        room = room_manager.get_room(session.get("room_id"))
        if room and room.game:
            await _emit_canvas_sync(room, sid)
