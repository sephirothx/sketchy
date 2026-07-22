"""Socket.IO event handlers: room lifecycle, game turns, drawing, guessing, chat."""
from __future__ import annotations

import asyncio
import logging

import socketio

from app.game import (
    DRAWING_SECONDS,
    CHOOSE_WORD_SECONDS,
    HINT_MODES,
    ROUND_END_SECONDS,
    Game,
    Phase,
)
from app.rooms import Player, Room, RoomFullError, RoomManager, STARTING_SCORE
from app.words import parse_custom_word_list

logger = logging.getLogger("sketchy.events")

RECONNECT_GRACE_SECONDS = 30

# Must match the frontend's Canvas.tsx CANVAS_WIDTH/CANVAS_HEIGHT - used only
# to sanity-check draw_fill patch bounds below.
CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600
# Generous cap on a base64-encoded fill patch: solid-color regions compress
# extremely well as PNG, so a legitimate fill of the whole canvas is nowhere
# near this size - this is purely a backstop against abusive payloads.
MAX_FILL_PATCH_CHARS = 300_000

# Per-room asyncio task driving the current phase's timeout (choosing/drawing/round-end).
_phase_timers: dict[str, asyncio.Task] = {}
# Per-room list of asyncio tasks that reveal checkpoint hint letters during drawing.
# Kept separate from _phase_timers so canceling one never cancels the other.
_hint_timers: dict[str, list[asyncio.Task]] = {}
# Per-player-token asyncio task that evicts a disconnected player after a grace period.
_disconnect_timers: dict[str, asyncio.Task] = {}


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def register_handlers(sio: socketio.AsyncServer, room_manager: RoomManager) -> None:
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

        # Reveal one extra letter to everyone when the drawing phase is 50%
        # and 25% of the way through (i.e. half, then a quarter, of the total
        # time remains).
        for remaining_fraction in (0.5, 0.25):
            delay = game.drawing_seconds * (1 - remaining_fraction)

            async def _runner(delay=delay, game=game) -> None:
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return
                if room.game is not game or game.phase != Phase.DRAWING:
                    return
                if game.reveal_hint_letter():
                    await sio.emit(
                        "hint_revealed", {"maskedWord": game.masked_word()}, room=room.id
                    )

            _hint_timers.setdefault(room.id, []).append(asyncio.create_task(_runner()))

    def cancel_disconnect_timer(token: str) -> None:
        task = _disconnect_timers.pop(token, None)
        if task and not task.done():
            task.cancel()

    async def _emit_room_state(room: Room) -> None:
        await sio.emit("room_state", room.to_state_payload(), room=room.id)

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
                _turn_payload(room.game, player.token),
                to=sid,
            )
            await sio.emit("sync_strokes", {"strokes": room.game.strokes}, to=sid)
            if player.token == room.game.current_drawer:
                await sio.emit(
                    "you_are_drawing",
                    {"word": room.game.word, "choices": room.game.word_choices},
                    to=sid,
                )

    def _turn_payload(game: Game, token: str | None = None) -> dict:
        return {
            "phase": game.phase.value,
            "drawerToken": game.current_drawer,
            "maskedWord": game.masked_word(token),
            "roundNumber": game.round_number,
            "totalRounds": game.rounds_total,
            "remainingSeconds": round(game.remaining_seconds()),
            "hintCost": game.hint_cost(token) if token else None,
        }

    async def _start_turn(room: Room) -> None:
        game = room.game
        assert game is not None
        choices = game.start_next_turn()
        game.set_phase_deadline(CHOOSE_WORD_SECONDS)
        drawer = room.players.get(game.current_drawer)
        await sio.emit("clear_canvas", {}, room=room.id)
        await sio.emit(
            "turn_starting",
            {
                "drawerToken": game.current_drawer,
                "drawerNickname": drawer.nickname if drawer else "",
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
        drawer = room.players.get(game.current_drawer)
        if drawer and drawer.sid:
            await sio.emit("you_are_drawing", {"word": game.word}, to=drawer.sid)
        # Sent per-player (rather than broadcast) because in "purchase" hint
        # mode each guesser may have their own set of bought letters revealed.
        for p in room.player_list():
            if not p.sid:
                continue
            await sio.emit(
                "turn_started",
                {
                    "drawerToken": game.current_drawer,
                    "maskedWord": game.masked_word(p.token),
                    "roundNumber": game.round_number,
                    "totalRounds": game.rounds_total,
                    "seconds": game.drawing_seconds,
                    "hintCost": game.hint_cost(p.token),
                },
                to=p.sid,
            )
        schedule_phase_timer(room, game.drawing_seconds)
        schedule_hint_checkpoints(room)

    async def _end_round(room: Room) -> None:
        game = room.game
        assert game is not None
        cancel_phase_timer(room.id)
        cancel_hint_timers(room.id)
        drawer_bonus = game.end_round()
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
                "scores": [
                    {
                        "token": p.token,
                        "nickname": p.nickname,
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

    async def _finish_or_next(room: Room) -> None:
        game = room.game
        assert game is not None
        if game.is_finished():
            room.state = "waiting"
            room.game = None
            await sio.emit(
                "game_ended",
                {
                    "scores": [
                        {"token": p.token, "nickname": p.nickname, "score": p.score}
                        for p in sorted(room.player_list(), key=lambda p: -p.score)
                    ]
                },
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
        player.connected = False
        player.sid = None
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
            was_drawer = bool(room.game and room.game.current_drawer == token)
            room_manager.remove_player(room, token)
            await sio.emit("player_left", {"token": token}, room=room.id)
            if not room.connected_players():
                cancel_phase_timer(room.id)
                room_manager.remove_room_if_empty(room.id)
                return
            if room.game:
                room.game.turn_order = [t for t in room.game.turn_order if t != token]
                if not room.game.turn_order:
                    room.state = "waiting"
                    room.game = None
                elif was_drawer:
                    await _start_turn(room)
            await _emit_room_state(room)

        _disconnect_timers[token] = asyncio.create_task(_evict_after_grace())

    # ------------------------------------------------------------------
    # Room lifecycle
    # ------------------------------------------------------------------

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
        name = str(data.get("name", "")).strip()[:40] or f"{nickname}'s game"
        is_public = bool(data.get("isPublic", True))
        max_players = _clamp(int(data.get("maxPlayers", 8) or 8), 2, 12)
        rounds = _clamp(int(data.get("rounds", 3) or 3), 1, 10)
        drawing_seconds = _clamp(int(data.get("drawingSeconds", DRAWING_SECONDS) or DRAWING_SECONDS), 15, 240)
        custom_words = parse_custom_word_list(str(data.get("customWords", "") or ""))
        custom_words_only = bool(data.get("customWordsOnly", False))
        hint_mode = str(data.get("hintMode", "none") or "none")
        if hint_mode not in HINT_MODES:
            hint_mode = "none"

        room = room_manager.create_room(
            name=name,
            is_public=is_public,
            max_players=max_players,
            rounds=rounds,
            custom_words=custom_words,
            custom_words_only=custom_words_only,
            drawing_seconds=drawing_seconds,
            hint_mode=hint_mode,
        )
        player = room_manager.add_player(room, nickname)
        await _join_socket_room(sid, room, player, is_reconnect=False)
        return {"ok": True, "roomId": room.id, "code": room.code, "token": player.token}

    @sio.event
    async def join_room(sid, data):
        data = data or {}
        token = data.get("token")
        room_id = data.get("roomId")
        code = data.get("code")
        nickname = str(data.get("nickname", "")).strip()[:20] or "Player"

        room = room_manager.get_room(room_id) or room_manager.get_room_by_code(code)
        if not room:
            return {"ok": False, "error": "Room not found"}

        if token and token in room.players:
            player = room.players[token]
            await _join_socket_room(sid, room, player, is_reconnect=True)
            return {"ok": True, "roomId": room.id, "code": room.code, "token": player.token}

        already_joined = await _existing_player_for_sid(sid, room.id)
        if already_joined:
            return {"ok": True, "roomId": room.id, "code": room.code, "token": already_joined.token}

        if room.state != "waiting":
            return {"ok": False, "error": "Game already in progress"}

        try:
            player = room_manager.add_player(room, nickname)
        except RoomFullError:
            return {"ok": False, "error": "Room is full"}

        await _join_socket_room(sid, room, player, is_reconnect=False)
        return {"ok": True, "roomId": room.id, "code": room.code, "token": player.token}

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
            room_manager.remove_room_if_empty(room.id)
        else:
            if room.game:
                room.game.turn_order = [t for t in room.game.turn_order if t != token]
            await sio.emit("player_left", {"token": token}, room=room.id)
            await _emit_room_state(room)

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
        if len(room.connected_players()) < 2:
            return {"ok": False, "error": "Need at least 2 players to start"}
        if room.state == "playing":
            return {"ok": False, "error": "Game already in progress"}

        for p in room.player_list():
            p.score = STARTING_SCORE
        room.state = "playing"
        room.game = Game(
            turn_order=[p.token for p in room.connected_players()],
            rounds_total=room.rounds,
            word_pool=room.effective_word_pool(),
            drawing_seconds=room.drawing_seconds,
            hint_mode=room.hint_mode,
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
            return
        token = session.get("token")
        word = str((data or {}).get("word", ""))
        if room.game.choose_word(token, word):
            cancel_phase_timer(room.id)
            await _begin_drawing(room)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    async def _broadcast_drawer_event(sid, event_name, data):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return
        token = session.get("token")
        if token != room.game.current_drawer:
            return
        room.game.record_stroke(event_name, data or {})
        await sio.emit(event_name, data or {}, room=room.id, skip_sid=sid)

    @sio.event
    async def draw_start(sid, data):
        await _broadcast_drawer_event(sid, "draw_start", data)

    @sio.event
    async def draw_move(sid, data):
        await _broadcast_drawer_event(sid, "draw_move", data)

    @sio.event
    async def draw_end(sid, data):
        await _broadcast_drawer_event(sid, "draw_end", data)

    @sio.event
    async def draw_shape(sid, data):
        await _broadcast_drawer_event(sid, "draw_shape", data)

    @sio.event
    async def draw_fill(sid, data):
        if not isinstance(data, dict):
            return
        patch_data = data.get("patchData")
        if not isinstance(patch_data, str) or not patch_data or len(patch_data) > MAX_FILL_PATCH_CHARS:
            return
        try:
            patch_x = int(data.get("patchX"))
            patch_y = int(data.get("patchY"))
            patch_width = int(data.get("patchWidth"))
            patch_height = int(data.get("patchHeight"))
        except (TypeError, ValueError):
            return
        if patch_width <= 0 or patch_height <= 0:
            return
        if patch_x < 0 or patch_y < 0:
            return
        if patch_x + patch_width > CANVAS_WIDTH or patch_y + patch_height > CANVAS_HEIGHT:
            return
        await _broadcast_drawer_event(sid, "draw_fill", data)

    @sio.event
    async def clear_canvas(sid, data=None):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return
        token = session.get("token")
        if token != room.game.current_drawer:
            return
        room.game.strokes = []
        # Unlike draw_start/move/end (where the drawer already renders locally as they
        # draw), the drawer has no local-only clear feedback, so broadcast to everyone
        # in the room including the sender.
        await sio.emit("clear_canvas", {}, room=room.id)

    @sio.event
    async def undo_stroke(sid, data=None):
        session = await sio.get_session(sid)
        room = room_manager.get_room(session.get("room_id")) if session else None
        if not room or not room.game:
            return
        token = session.get("token")
        if token != room.game.current_drawer:
            return
        if room.game.undo_last_stroke():
            # The canvas is a raster, so the only way to "undo" a stroke for
            # everyone (including the drawer, who already rendered it
            # locally) is a full clear + replay of what remains - reusing
            # the same sync_strokes event used to catch up new joiners.
            await sio.emit("sync_strokes", {"strokes": room.game.strokes}, room=room.id)

    # ------------------------------------------------------------------
    # Guessing / chat
    # ------------------------------------------------------------------

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

        game = room.game
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
                    and (p.token in game.correct_guessers or p.token == game.current_drawer)
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
            if p.sid and (p.token in game.correct_guessers or p.token == game.current_drawer)
        ]
        for target_sid in in_the_know:
            await sio.emit(
                "chat_message",
                {"token": player.token, "nickname": player.nickname, "text": text, "correct": True},
                to=target_sid,
            )

        guesser_count = len([p for p in room.connected_players() if p.token != game.current_drawer])
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
