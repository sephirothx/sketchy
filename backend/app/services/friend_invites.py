"""Invitations one seated player sends another, and how long they last.

Process-owned and never durable, like the presence registry and everything
else about a live room: an invitation to a room that no longer exists is not
worth restoring, and a restart takes the rooms with it anyway.

An invitation carries **no room code, name, or id** - only who sent it and a
token. The recipient's client answers by naming the token back, and the server
resolves the room from the sender's live seat at that moment. So the thing on
the wire is a capability to *ask*, not a capability to *enter*: it cannot be
forwarded to somebody it was not addressed to, it stops working when the sender
leaves, and it never tells anybody the code of a room they were not seated in.

Single use. An invitation that could be redeemed twice is a bearer token for a
private room with a two-minute life, which is exactly what R-ROOM-02 keeps room
codes from becoming.
"""
from __future__ import annotations

from dataclasses import dataclass
import secrets
import time

# Long enough to notice a toast and decide; short enough that an invitation
# forgotten in a closed tab is not a way in an hour later.
DEFAULT_TTL_SECONDS = 120
# One process, bounded. Far above what a lobby full of people can produce in
# two minutes, and low enough that nothing can grow without limit here.
MAX_OPEN_INVITES = 2048


@dataclass(frozen=True, slots=True)
class FriendInvite:
    token: str
    from_user_id: str
    to_user_id: str
    expires_at: float

    def is_live(self, now: float) -> bool:
        return now < self.expires_at


class FriendInviteBook:
    """The invitations currently outstanding, keyed by their token."""

    def __init__(self, *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._invites: dict[str, FriendInvite] = {}

    def issue(self, from_user_id: str, to_user_id: str, *, now: float | None = None) -> FriendInvite:
        """Mint an invitation from one account to another.

        Replaces any invitation already outstanding between the same two, so
        pressing the button twice is one live invitation rather than two - and
        so the count cannot be grown by a single pair.
        """
        moment = time.monotonic() if now is None else now
        self._expire(moment)
        for token, invite in list(self._invites.items()):
            if invite.from_user_id == from_user_id and invite.to_user_id == to_user_id:
                del self._invites[token]
        invite = FriendInvite(
            token=secrets.token_urlsafe(16),
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            expires_at=moment + self.ttl_seconds,
        )
        self._invites[invite.token] = invite
        while len(self._invites) > MAX_OPEN_INVITES:
            # Oldest first: dicts keep insertion order, and the oldest
            # invitation is the one closest to expiring anyway.
            self._invites.pop(next(iter(self._invites)))
        return invite

    def redeem(self, token: str, to_user_id: str, *, now: float | None = None) -> FriendInvite | None:
        """Spend an invitation, or answer `None` if it is not this caller's.

        Checks the recipient rather than trusting the token alone: a token that
        worked for whoever presented it would be forwardable, and forwardable is
        the property this whole design is avoiding.
        """
        moment = time.monotonic() if now is None else now
        self._expire(moment)
        invite = self._invites.get(token)
        if invite is None or invite.to_user_id != to_user_id:
            return None
        del self._invites[token]
        return invite

    def revoke_all_from(self, from_user_id: str) -> None:
        """Drop everything this account has outstanding.

        Called when they lose their seat: an invitation is to a game they are
        in, and once they are not in it there is nothing to accept.
        """
        for token, invite in list(self._invites.items()):
            if invite.from_user_id == from_user_id:
                del self._invites[token]

    def _expire(self, now: float) -> None:
        for token, invite in list(self._invites.items()):
            if not invite.is_live(now):
                del self._invites[token]

    def outstanding(self) -> int:
        return len(self._invites)
