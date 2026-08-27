"""Helpers shared by the handler test modules."""
from __future__ import annotations

from unittest.mock import AsyncMock

import socketio

from app.game import Game
from app.handlers import register_all_handlers as register_handlers
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


def canvas_action(game: Game, sequence: int) -> list[int]:
    """The [generation, sequence] pair a draw payload is stamped with."""
    return [game.canvas.generation, sequence]


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


def build_context(room_manager, history_repo, prompt_list_repo=None, timeline=None):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(
        sio,
        room_manager,
        game_history_repo=history_repo,
        prompt_list_repo=prompt_list_repo,
    )
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


class SessionStore:
    """Socket sessions that persist, for flows that cross rooms.

    ``AsyncServer.save_session`` is mocked away in most handler tests because
    nothing reads it back. A socket moving between rooms does, and the value
    it reads has to be the one the previous handler wrote.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}

    async def get(self, sid, namespace=None) -> dict:
        return self.sessions.setdefault(sid, {})

    async def save(self, sid, session, namespace=None) -> None:
        self.sessions[sid] = dict(session)
