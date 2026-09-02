"""Friends, from inside the game: adding one, inviting one, joining one.

Three commands, and the interesting thing is that two of them let somebody into
a room they cannot name - so the rule for *who* may do that is the whole
design.

**An invitation is not weaker than what already exists.** Anybody seated can
already paste the room code into a chat window; R-ROOM-02 makes the code a
bearer capability precisely so that it can be shared. `invite_friend` is a
tighter version of that same gesture: it carries no code, it is addressed to
one account, it is single use, and it dies in two minutes. So any seated player
may send one.

**Pulling yourself in is new, so it is held to the host.** Presence says a
friend is *in a game*, and `join_friend_room` without an invitation turns that
into a seat. Nobody chose to let that person in - which is fine when the room
is the host's own and the host is your friend, and is not fine when it means a
private room gains a fifth person because one of the four occupants knows them.
So an uninvited join resolves only rooms whose **host** is an accepted friend
of the caller.

Neither path ever sends a room code to somebody who has not been seated. Both
re-check blocks at the moment of use: a friendship read a moment ago is not a
licence, and a block placed in between has to win.
"""
from __future__ import annotations

from functools import partial
import logging
from uuid import UUID

from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    AddFriendPayload,
    FriendUserPayload,
    JoinFriendRoomPayload,
    PayloadError,
    parse_payload,
)
from app.handlers.rooms import (
    BUSY_ACKNOWLEDGEMENT,
    EntryTimedOut,
    _after_seating,
    _bounded,
    _seat_in_room,
)
from app.services.friends import (
    REGISTER_FIRST,
    FriendshipOutcome,
    FriendshipRefused,
)

logger = logging.getLogger("sketchy.handlers.friends")

#: The same wording the REST refusal carries, from the same constant.
REGISTER_FIRST_ACK = {"ok": False, "error": REGISTER_FIRST}
NOT_IN_A_GAME = {"ok": False, "error": "Your friend is not in a game right now."}
# Deliberately the same answer for "we are not friends" and "there is no such
# account": neither is a fact this caller is owed, and telling them apart makes
# the command a way to test whether somebody has unfriended you.
NOT_FRIENDS = {"ok": False, "error": "You can only join a friend's game."}


def _account_of(session) -> str | None:
    return session.get("user_id") if session else None


async def _uuid_or_none(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


async def add_friend(ctx: HandlerContext, sid, data):
    """Send a friend request to somebody sitting in the same room.

    Named by seat, so no account id crosses the wire in either direction
    (R-ROOM-07). This is the moment people actually want the button: you have
    just played with somebody, and the lobby is where you would otherwise have
    to go and find them again.
    """
    try:
        payload = parse_payload(AddFriendPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, me = current
    if ctx.friend_service is None:
        return {"ok": False, "error": "Friends are unavailable right now."}

    target = room.players.get(payload.player_id)
    if target is None or target.id == me.id:
        # One answer for "no such seat" and "that is you", the way
        # `report_player` does it: a report is not a way to find out who is in
        # a room you cannot see, and neither is a friend request.
        return {"ok": True}
    if me.is_anonymous or not me.user_id:
        return REGISTER_FIRST_ACK
    if not target.user_id:
        return {"ok": True}

    mine = await _uuid_or_none(me.user_id)
    theirs = await _uuid_or_none(target.user_id)
    if mine is None or theirs is None:
        return {"ok": True}
    try:
        outcome = await _bounded(
            ctx.friend_service.request(mine, theirs), "sending a friend request"
        )
    except EntryTimedOut:
        return BUSY_ACKNOWLEDGEMENT
    except FriendshipRefused as refused:
        return {"ok": False, "error": str(refused)}
    # Only the two outcomes that changed something are named. Everything else -
    # already friends, already asked, or a block - answers the same, so the
    # command cannot be used to tell those apart.
    reported = (
        outcome.value
        if outcome in (FriendshipOutcome.CREATED, FriendshipOutcome.ACCEPTED)
        else "unchanged"
    )
    return {"ok": True, "status": reported}


async def invite_friend(ctx: HandlerContext, sid, data):
    """Invite a friend into the game this socket is seated in."""
    try:
        payload = parse_payload(FriendUserPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current:
        return {"ok": False, "error": "Not in this room"}
    room, me = current
    if ctx.friend_service is None or ctx.friend_invites is None:
        return {"ok": False, "error": "Friends are unavailable right now."}
    if me.is_anonymous or not me.user_id:
        return REGISTER_FIRST_ACK

    mine = await _uuid_or_none(me.user_id)
    theirs = await _uuid_or_none(payload.friend_user_id)
    if mine is None or theirs is None or mine == theirs:
        return NOT_FRIENDS
    try:
        allowed = await _bounded(
            ctx.friend_service.are_friends(mine, theirs), "reading a friendship"
        )
        blocked = allowed and await _bounded(
            ctx.friend_service.is_blocked_pair(mine, theirs), "reading blocks"
        )
    except EntryTimedOut:
        return BUSY_ACKNOWLEDGEMENT
    if not allowed or blocked:
        return NOT_FRIENDS

    # The room this *socket* is seated in, from `require_current_player` above.
    # Not "a room this account is in": one account may hold seats in two rooms
    # on two tabs (R-ROOM-08), and an invitation sent from one of them must not
    # name the other.
    invite = ctx.friend_invites.issue(me.user_id, payload.friend_user_id, room.id)
    await ctx.sio.emit(
        "friend_invite_received",
        {
            "fromUserId": me.user_id,
            "displayName": me.nickname,
            "inviteToken": invite.token,
            "expiresIn": int(ctx.friend_invites.ttl_seconds),
        },
        room=f"user:{payload.friend_user_id}",
    )
    return {"ok": True}


async def join_friend_room(ctx: HandlerContext, sid, data):
    """Take a seat wherever a friend is, without ever naming the room."""
    seated: list = []
    async with ctx.seating(sid):
        answer = await _join_friend_room(ctx, sid, data, seated)
    await _after_seating(ctx, seated)
    return answer


async def _join_friend_room(ctx: HandlerContext, sid, data, seated: list):
    try:
        payload = parse_payload(JoinFriendRoomPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    if ctx.friend_service is None:
        return {"ok": False, "error": "Friends are unavailable right now."}

    session = await ctx.sio.get_session(sid) if sid else None
    account = _account_of(session)
    if not account:
        return {"ok": False, "error": "Sign in to join a friend's game."}
    mine = await _uuid_or_none(account)
    theirs = await _uuid_or_none(payload.friend_user_id)
    if mine is None or theirs is None or mine == theirs:
        return NOT_FRIENDS

    # Read, not yet spent. An invitation is one use, and burning it to answer
    # "that game has ended" would leave the recipient with nothing - so the
    # room is checked first and the token spent only once it can be honoured.
    invite = None
    if payload.invite_token and ctx.friend_invites is not None:
        invite = ctx.friend_invites.peek(payload.invite_token, account)
        if invite is None:
            return {"ok": False, "error": "That invitation has expired."}
        if invite.from_user_id != payload.friend_user_id:
            return NOT_FRIENDS

    try:
        allowed = await _bounded(
            ctx.friend_service.are_friends(mine, theirs), "reading a friendship"
        )
        # Belt and braces: blocking already deletes the friendship in the same
        # transaction as the block, so this should never fire. It is logged if
        # it does, because that means the delete did not run.
        blocked = allowed and await _bounded(
            ctx.friend_service.is_blocked_pair(mine, theirs), "reading blocks"
        )
    except EntryTimedOut:
        return BUSY_ACKNOWLEDGEMENT
    if blocked:
        logger.warning(
            "a friendship survived a block between %s and %s", mine, theirs
        )
        return NOT_FRIENDS
    if not allowed:
        return NOT_FRIENDS

    if invite is not None:
        # An invitation names its room, so there is nothing to search for. It
        # is good only while its sender is still sitting in that room: one who
        # left and joined another would otherwise have handed out a way into
        # the second, which nobody offered.
        room = ctx.room_manager.get_room(invite.room_id)
        if room is None or not _is_seated(room, payload.friend_user_id):
            return NOT_IN_A_GAME
    else:
        # Uninvited, so nobody in the room chose to let this caller in and the
        # host's friendship is the only consent there is. The friend may be in
        # two rooms at once (R-ROOM-08), and picking whichever comes first
        # would resolve a different game from one call to the next - so the
        # candidates are filtered and an ambiguous answer is refused rather
        # than guessed.
        try:
            candidates = await _joinable_rooms(ctx, mine, payload.friend_user_id)
        except EntryTimedOut:
            return BUSY_ACKNOWLEDGEMENT
        if not candidates:
            if _rooms_of(ctx, payload.friend_user_id):
                return {
                    "ok": False,
                    "error": "Only the host's friends can join this game "
                    "uninvited. Ask them for an invite.",
                }
            return NOT_IN_A_GAME
        if len(candidates) > 1:
            # Two games, one button, and no way to know which was meant. An
            # invitation names one, which is the way out of this.
            return {
                "ok": False,
                "error": "That friend is in more than one game. "
                "Ask them for an invite.",
            }
        room = candidates[0]

    answer = await _seat_in_room(ctx, sid, room, payload, seated)
    # Spent only once there is a seat. `_seat_in_room` refuses for half a dozen
    # reasons after this point - the room filled, a rate limit, an identity
    # that would not resolve - and burning the one use on any of them would
    # leave the recipient unable to try again a moment later.
    if invite is not None and answer.get("ok"):
        ctx.friend_invites.redeem(payload.invite_token, account)
    return answer


def _is_seated(room, user_id: str) -> bool:
    return any(player.user_id == user_id for player in room.players.values())


def _rooms_of(ctx: HandlerContext, user_id: str) -> list:
    """Every live room this account is seated in, with who hosts each.

    A list, not the first match: seats are matched by socket rather than by
    account (R-ROOM-08), so two tabs of one account in two rooms is ordinary
    rather than a fault. A caller that took the first would resolve a
    different game depending on dictionary order.

    One pass over the rooms rather than an index, the way presence derives its
    status: a few hundred comparisons at the product ceiling, and nothing that
    can stop being true.
    """
    found = []
    for room in list(ctx.room_manager.rooms.values()):
        seats = list(room.players.values())
        if not any(player.user_id == user_id for player in seats):
            continue
        host = next((player for player in seats if player.is_host), None)
        found.append((room, host.user_id if host else None))
    return found


async def _joinable_rooms(ctx: HandlerContext, mine, friend_user_id: str) -> list:
    """The rooms holding this friend that the caller may enter uninvited.

    Which is to say: the ones whose host is a friend of the caller. A room the
    named friend hosts qualifies without another lookup - they have already
    been checked.
    """
    joinable = []
    for room, host_user_id in _rooms_of(ctx, friend_user_id):
        if host_user_id is None:
            continue
        if host_user_id == friend_user_id:
            joinable.append(room)
            continue
        host = await _uuid_or_none(host_user_id)
        if host is None:
            continue
        if await _bounded(
            ctx.friend_service.are_friends(mine, host), "reading a friendship"
        ):
            joinable.append(room)
    return joinable


def register(ctx: HandlerContext) -> None:
    ctx.on("add_friend", handler=partial(add_friend, ctx))
    ctx.on("invite_friend", handler=partial(invite_friend, ctx))
    ctx.on("join_friend_room", handler=partial(join_friend_room, ctx))
