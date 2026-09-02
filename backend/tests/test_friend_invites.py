"""Outstanding invitations: what expires, what is spent, and what is bounded.

An invitation is the one thing in the friends feature that acts like a token,
so the properties worth pinning are the ones that keep it from acting like a
room code: single use, addressed, short-lived, and bounded in number.
"""
from __future__ import annotations

from app.services.friend_invites import MAX_OPEN_INVITES, FriendInviteBook

ADA, BOB, CAT = "user-ada", "user-bob", "user-cat"
ROOM, OTHER_ROOM = "room-1", "room-2"


def test_an_invitation_is_spent_by_the_account_it_was_addressed_to():
    book = FriendInviteBook()
    invite = book.issue(ADA, BOB, ROOM, now=0)

    # Not by anyone else, however they came by the token: forwardable is the
    # property this whole design exists to avoid.
    assert book.redeem(invite.token, CAT, now=1) is None
    assert book.redeem(invite.token, BOB, now=1) is not None
    # And not twice.
    assert book.redeem(invite.token, BOB, now=1) is None
    assert book.outstanding() == 0


def test_an_invitation_stops_working_when_it_runs_out():
    book = FriendInviteBook(ttl_seconds=60)
    invite = book.issue(ADA, BOB, ROOM, now=0)

    assert book.redeem(invite.token, BOB, now=59) is not None
    other = book.issue(ADA, CAT, ROOM, now=0)
    assert book.redeem(other.token, CAT, now=61) is None
    assert book.outstanding() == 0


def test_an_unknown_token_is_simply_not_an_invitation():
    book = FriendInviteBook()
    assert book.redeem("never-issued", BOB) is None


def test_asking_twice_leaves_one_invitation_rather_than_two():
    """So a single pair cannot grow the book by pressing a button."""
    book = FriendInviteBook()
    first = book.issue(ADA, BOB, ROOM, now=0)
    second = book.issue(ADA, BOB, ROOM, now=1)

    assert book.outstanding() == 1
    assert book.redeem(first.token, BOB, now=2) is None
    assert book.redeem(second.token, BOB, now=2) is not None


def test_an_invitation_remembers_which_room_it_was_sent_from():
    """So it cannot follow its sender into a different one.

    Nothing revokes an invitation when a seat is lost, deliberately: that
    would be one more thing every teardown path has to remember. The room is
    part of the invitation instead, and the handler refuses one whose room the
    sender is no longer in.
    """
    book = FriendInviteBook()
    invite = book.issue(ADA, BOB, ROOM, now=0)

    assert invite.room_id == ROOM
    # And it is nowhere on the wire - the handler reads it, the client never
    # sees it. `tests/handlers/test_friends.py` pins that.
    assert book.peek(invite.token, BOB, now=1).room_id == ROOM


def test_reading_an_invitation_does_not_spend_it():
    """One use, and answering "that game has ended" must not be the use."""
    book = FriendInviteBook()
    invite = book.issue(ADA, BOB, ROOM, now=0)

    assert book.peek(invite.token, BOB, now=1) is not None
    assert book.peek(invite.token, BOB, now=1) is not None
    assert book.outstanding() == 1
    assert book.redeem(invite.token, BOB, now=1) is not None
    assert book.peek(invite.token, BOB, now=1) is None


def test_the_book_is_bounded():
    book = FriendInviteBook()
    for index in range(MAX_OPEN_INVITES + 50):
        book.issue(ADA, f"user-{index}", ROOM, now=0)
    assert book.outstanding() == MAX_OPEN_INVITES


def test_expiry_is_swept_on_use_rather_than_by_a_loop():
    """Nothing schedules cleanup, so the next caller has to do it."""
    book = FriendInviteBook(ttl_seconds=10)
    book.issue(ADA, BOB, ROOM, now=0)
    book.issue(ADA, CAT, ROOM, now=0)
    assert book.outstanding() == 2

    book.issue(CAT, ADA, ROOM, now=100)
    assert book.outstanding() == 1
