"""Resolve the account behind a socket into the name and status it plays under."""
from __future__ import annotations

from dataclasses import dataclass

from app.auth.names import NameError_, validate_name
from app.handlers.context import HandlerContext


@dataclass(frozen=True)
class PlayerIdentity:
    """How a socket should appear in a room."""

    user_id: str | None
    nickname: str
    is_anonymous: bool


class IdentityError(ValueError):
    """A name the caller is not allowed to play under."""


async def resolve_identity(
    ctx: HandlerContext, sid: str, requested_nickname: str
) -> PlayerIdentity:
    """Decide the name and status for this socket's next seat.

    A registered player always plays as their username - the requested nickname
    is ignored - so a name shown in the player list is either a claimed account
    or an unclaimed guest, never one impersonating the other. A guest may pick
    any name that is not already a registered username.
    """
    session = await ctx.sio.get_session(sid) if sid else None
    user_id = session.get("user_id") if session else None

    user = None
    if user_id and ctx.user_repo is not None:
        user = await ctx.user_repo.get_by_id(user_id)

    if user is not None and not user.is_anonymous and user.username:
        return PlayerIdentity(
            user_id=user.id, nickname=user.username, is_anonymous=False
        )

    if user is not None:
        # The account is the authority for a guest's name. Trusting the socket
        # payload instead would let a client play under any name it liked.
        if not user.display_name:
            # Still on their first run. The client asks for a name before it
            # offers to create or join, so reaching here means something went
            # around the UI - never seat a nameless player.
            raise IdentityError("Choose a name before joining a room.")
        return PlayerIdentity(
            user_id=user.id, nickname=user.display_name, is_anonymous=True
        )

    # No account at all (cookies blocked): fall back to whatever they asked
    # for, still subject to the shared rule.
    try:
        nickname = validate_name(requested_nickname)
    except NameError_ as error:
        raise IdentityError(str(error)) from error

    if ctx.user_repo is not None:
        owner = await ctx.user_repo.get_by_username(nickname)
        if owner is not None and not owner.is_anonymous:
            raise IdentityError("That name belongs to a registered player.")

    return PlayerIdentity(user_id=user_id, nickname=nickname, is_anonymous=True)
