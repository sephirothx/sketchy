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

    try:
        nickname = validate_name(requested_nickname)
    except NameError_ as error:
        raise IdentityError(str(error)) from error

    # Two guests may share a nickname - it is not an identity - but neither may
    # wear a name someone has actually claimed.
    if ctx.user_repo is not None:
        owner = await ctx.user_repo.get_by_username(nickname)
        if owner is not None and not owner.is_anonymous:
            raise IdentityError("That name belongs to a registered player.")

    return PlayerIdentity(
        user_id=user.id if user else user_id,
        nickname=nickname,
        is_anonymous=True,
    )
