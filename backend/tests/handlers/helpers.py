"""Helpers shared by the handler test modules."""
from __future__ import annotations

from app.game import Game

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

    The credential is now the JWT in the session cookie rather than a per-room
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
