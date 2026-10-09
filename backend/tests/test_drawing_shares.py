"""Sharing a drawing to the Gallery (#1430): who may, what it takes back, what
it tells the drawer, and how every other surface follows it."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.api.inbox import inbox_payload
from app.auth.account_data import anonymize_account
from app.db.models import (
    InboxEntry,
    ProfileDrawingPin,
    TurnDrawing,
    TurnDrawingShare,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.gallery_ranking import rebuild_gallery_ranking
from app.services.integrity_audit import _drawing_projections_slice
from tests.dbfixtures import create_test_db
from tests.test_drawing_reactions import record_game, registered


NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def repos():
    factory, engine = await create_test_db()
    try:
        yield (
            SqlAlchemyUserRepository(factory),
            SqlAlchemyGameHistoryRepository(factory),
            factory,
        )
    finally:
        await engine.dispose()


async def _gallery_ids(history) -> list[str]:
    return [entry.turn_id for entry in (await history.list_gallery(sort="new")).entries]


async def _notices(factory) -> list[tuple[UUID, UUID]]:
    """The inbox entries that tell a drawer about a share (#1436)."""
    async with factory() as session:
        rows = (
            await session.scalars(select(InboxEntry).where(InboxEntry.kind == "drawing_shared"))
        ).all()
    return [(row.user_id, row.subject_id) for row in rows]


async def _told(factory, user_id: str) -> list[tuple[str, str | None]]:
    """What the drawer's inbox shows: each entry's drawing and the name on it,
    read now from the shares still standing - nobody once none is left."""
    payload = await inbox_payload(factory, user_id)
    return [
        (entry["drawing"]["turnId"], (entry["drawing"]["sharedBy"] or {}).get("displayName"))
        for entry in payload["entries"]
        if entry["kind"] == "drawing_shared"
    ]


async def _drawing(factory, turn_id: str) -> TurnDrawing:
    async with factory() as session:
        return await session.get(TurnDrawing, UUID(turn_id))


async def test_nothing_is_in_the_gallery_until_somebody_shares_it(repos):
    """R-SHARE-01: a public game's drawing is not published by being played."""
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
        finished_at=NOW - timedelta(hours=1),
    )
    assert await _gallery_ids(history) == []
    assert await history.get_gallery_entry(game.turn_id) is None
    assert await history.get_gallery_drawing(game.turn_id) is None

    shared = await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    )
    assert shared is not None and shared.shares == (game.reactor_seat,)
    assert await _gallery_ids(history) == [game.turn_id]
    assert await history.get_gallery_drawing(game.turn_id) is not None


async def test_who_may_share_follows_the_room_and_the_drawer(repos):
    """R-SHARE-02: the drawer from any game, anyone else who sat in it only
    from a public one, nobody who was not there."""
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    cid = await registered(users, "Cid")
    private = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="private",
        finished_at=NOW - timedelta(hours=2),
    )
    public = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
        finished_at=NOW - timedelta(hours=1),
    )

    assert await history.set_drawing_share(
        private.game_id, private.turn_id, requesting_user_id=bob.id, shared=True
    ) is None, "a private room's drawing leaves it only by its maker's hand"
    assert await history.set_drawing_share(
        public.game_id, public.turn_id, requesting_user_id=cid.id, shared=True
    ) is None, "nobody who was not there"
    assert await history.set_drawing_share(
        None, public.turn_id, requesting_user_id=cid.id, shared=False
    ) is None, "not from the Gallery's door either"
    assert await history.set_drawing_share(
        public.game_id, private.turn_id, requesting_user_id=ann.id, shared=True
    ) is None, "the turn must belong to the game named"

    assert await history.set_drawing_share(
        private.game_id, private.turn_id, requesting_user_id=ann.id, shared=True
    )
    entry = await history.get_gallery_entry(private.turn_id, requesting_user_id=cid.id)
    assert entry is not None and entry.shared_by_drawer and entry.sharer_display_name is None


async def test_a_guest_who_played_may_share(repos):
    users, history, _ = repos
    ann = await registered(users, "Ann")
    guest = await users.create_anonymous(display_name="Guest")
    game = await record_game(
        history, drawer=ann.id, reactor=guest.id, reactor_is_anonymous=True,
        visibility="public", shared_by=None,
    )
    assert await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=guest.id, shared=True
    )
    entry = await history.get_gallery_entry(game.turn_id, requesting_user_id=guest.id)
    assert entry.sharer_display_name == "Reactor" and entry.sharer_is_anonymous
    assert entry.shared_by_me and not entry.drawn_by_me


async def test_a_blank_hidden_or_unkept_drawing_cannot_be_shared(repos):
    """R-SHARE-03: an empty canvas from an abandoned turn is nothing anyone
    meant to show, and a hidden one stays a moderator's to release."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    blank = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
        stroke_count=0,
    )
    unkept = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
        drawing=False,
    )
    hidden = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    async with factory() as session:
        await session.execute(
            update(TurnDrawing)
            .where(TurnDrawing.turn_id == UUID(hidden.turn_id))
            .values(gallery_hidden_at=NOW)
        )
        await session.commit()
    for game in (blank, unkept, hidden):
        for who in (ann, bob):
            assert await history.set_drawing_share(
                game.game_id, game.turn_id, requesting_user_id=who.id, shared=True
            ) is None
    # Taking back is always allowed, and harmless where nothing was shared.
    assert await history.set_drawing_share(
        hidden.game_id, hidden.turn_id, requesting_user_id=bob.id, shared=False
    )


async def test_the_drawers_withdrawal_takes_every_share_and_pin_and_holds(repos):
    """R-SHARE-04: the drawer's withdrawal is everybody's, until the drawer
    shares it again."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by="reactor",
    )
    assert await history.set_profile_pins(requesting_user_id=bob.id, turn_ids=[game.turn_id])
    assert await _gallery_ids(history) == [game.turn_id]

    withdrawn = await history.set_drawing_share(
        None, game.turn_id, requesting_user_id=ann.id, shared=False
    )
    assert withdrawn is not None and withdrawn.shares == () and withdrawn.withdrawn
    assert await _gallery_ids(history) == []
    assert await history.get_profile_pins(bob.id) == ()
    async with factory() as session:
        assert (await session.scalars(select(ProfileDrawingPin))).all() == []
    row = await _drawing(factory, game.turn_id)
    assert row.gallery_share_count == 0 and row.gallery_withdrawn_at is not None

    assert await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    ) is None, "nobody else may share it again"
    assert await history.set_profile_pins(
        requesting_user_id=bob.id, turn_ids=[game.turn_id]
    ) is None, "nor pin it, since a pin is a share"

    again = await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=ann.id, shared=True
    )
    assert again.shares == (game.drawer_seat,) and not again.withdrawn
    assert await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    ), "once the drawer shares it again, so may anyone"


async def test_a_sharer_takes_back_only_their_own_share_and_pin(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by=("drawer", "reactor"),
    )
    assert await history.set_profile_pins(requesting_user_id=bob.id, turn_ids=[game.turn_id])
    first = (await _drawing(factory, game.turn_id)).gallery_shared_at

    taken = await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=False
    )
    assert taken.shares == (game.drawer_seat,) and not taken.withdrawn
    assert await history.get_profile_pins(bob.id) == ()
    assert await _gallery_ids(history) == [game.turn_id], "the drawer's share holds it"
    assert (await _drawing(factory, game.turn_id)).gallery_shared_at == first

    # The drawer shared first; with the drawer's own share gone too, it leaves.
    await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    )
    async with factory() as session:
        await session.execute(
            TurnDrawingShare.__table__.delete().where(
                TurnDrawingShare.participant_id == UUID(game.drawer_seat)
            )
        )
        await session.commit()
    await rebuild_gallery_ranking(factory)
    kept = await _drawing(factory, game.turn_id)
    assert kept.gallery_share_count == 1
    assert kept.gallery_shared_at == first, "the first entry is kept, not moved later"
    await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=False
    )
    assert await _gallery_ids(history) == []


async def test_the_gallery_credits_the_first_sharer_and_orders_by_the_first_share(repos):
    """R-SHARE-06: New is the order drawings entered the Gallery, not the order
    their games finished - a drawing shared from history today is new today."""
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    old = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
        finished_at=NOW - timedelta(days=20),
    )
    recent = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by=("reactor", "drawer"), finished_at=NOW - timedelta(hours=2),
    )
    assert await _gallery_ids(history) == [recent.turn_id]
    entry = await history.get_gallery_entry(recent.turn_id, requesting_user_id=ann.id)
    assert entry.sharer_display_name == "Reactor" and not entry.shared_by_drawer
    assert entry.shared_by_me, "the drawer shared it too"

    await history.set_drawing_share(
        old.game_id, old.turn_id, requesting_user_id=bob.id, shared=True
    )
    assert await _gallery_ids(history) == [old.turn_id, recent.turn_id]
    hot = [entry.turn_id for entry in (await history.list_gallery(sort="hot")).entries]
    assert old.turn_id in hot, "inside Hot's horizon from the share, not the finish"
    week = [
        entry.turn_id
        for entry in (await history.list_gallery(sort="top", window="week")).entries
    ]
    assert old.turn_id in week


async def test_a_share_leaves_the_drawer_one_notice_unless_they_saw_it(repos):
    """R-SHARE-09: the first share by somebody else, once per drawing; never
    the drawer's own; not where the drawer was watching."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    watched = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    own = await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=ann.id, shared=True
    )
    assert own.notify_user_id is None and await _notices(factory) == []

    told = await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    )
    assert told.notify_user_id == ann.id
    assert await _notices(factory) == [(UUID(ann.id), UUID(game.turn_id))]
    assert await _told(factory, ann.id) == [(game.turn_id, "Reactor")]
    await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=False
    )
    again = await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    )
    assert again.notify_user_id is None and len(await _notices(factory)) == 1

    seen = await history.set_drawing_share(
        watched.game_id, watched.turn_id, requesting_user_id=bob.id, shared=True,
        notify_drawer=False,
    )
    assert seen.notify_user_id is None and len(await _notices(factory)) == 1


async def test_the_drawers_withdrawal_settles_the_notice(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    )
    await history.set_drawing_share(None, game.turn_id, requesting_user_id=ann.id, shared=False)
    async with factory() as session:
        [notice] = (
            await session.scalars(select(InboxEntry).where(InboxEntry.kind == "drawing_shared"))
        ).all()
    assert notice.read_at is not None, "taking it out is acting on it"


async def test_pinning_shares_and_tells_the_drawer(repos):
    """R-PIN-03: a pin is a share - the pinner's, with the share's rules."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    public = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    private = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="private", shared_by=None,
    )
    assert await history.set_profile_pins(
        requesting_user_id=bob.id, turn_ids=[private.turn_id]
    ) is None, "somebody else's private drawing is not theirs to share"

    pinned = await history.set_profile_pins(requesting_user_id=bob.id, turn_ids=[public.turn_id])
    assert pinned.notify_user_ids == (ann.id,)
    assert await _gallery_ids(history) == [public.turn_id]
    [entry] = await history.get_profile_pins(bob.id)
    assert entry.turn_id == public.turn_id

    # The drawer may pin their own private drawing: it shares it.
    mine = await history.set_profile_pins(requesting_user_id=ann.id, turn_ids=[private.turn_id])
    assert mine.notify_user_ids == ()
    assert private.turn_id in await _gallery_ids(history)
    # Unpinning keeps the share: the two are separate acts after the first.
    await history.set_profile_pins(requesting_user_id=bob.id, turn_ids=[])
    assert public.turn_id in await _gallery_ids(history)
    async with factory() as session:
        sharers = (await session.scalars(select(TurnDrawingShare.user_id))).all()
    assert sorted(map(str, sharers)) == sorted([ann.id, bob.id])


async def test_erasing_a_sharer_takes_their_shares_and_their_name_off_the_notice(repos):
    """R-SHARE-08: a share is the sharer's act, and their name is its credit."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None,
    )
    await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    )
    assert await _told(factory, ann.id) == [(game.turn_id, "Reactor")]
    await anonymize_account(factory, user_id=bob.id)
    assert await _gallery_ids(history) == []
    assert await _told(factory, ann.id) == [(game.turn_id, None)], "an entry naming nobody"
    row = await _drawing(factory, game.turn_id)
    assert row.gallery_share_count == 0 and row.hot_score == 0.0
    assert await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=True
    ) is None, "a tombstoned account shares nothing"


async def test_erasing_a_drawer_takes_every_share_of_their_drawings(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by=("drawer", "reactor"),
    )
    await anonymize_account(factory, user_id=ann.id)
    async with factory() as session:
        assert (await session.scalars(select(TurnDrawingShare))).all() == []
    assert await _gallery_ids(history) == []


async def test_the_audit_and_the_rebuild_agree_on_the_first_share(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by="reactor",
    )
    async with factory() as session:
        assert (await _drawing_projections_slice(session, None)).mismatches == []
        await session.execute(
            update(TurnDrawing)
            .where(TurnDrawing.turn_id == UUID(game.turn_id))
            .values(gallery_shared_at=None)
        )
        await session.commit()
    async with factory() as session:
        [mismatch] = (await _drawing_projections_slice(session, None)).mismatches
        assert mismatch.kind == "gallery_shared_at"
    await rebuild_gallery_ranking(factory)
    async with factory() as session:
        assert (await _drawing_projections_slice(session, None)).mismatches == []


# ----------------------------------------------------------------- the fold


async def test_live_shares_are_written_with_the_game(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    finished = NOW - timedelta(hours=1)
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by="reactor", finished_at=finished,
    )
    row = await _drawing(factory, game.turn_id)
    assert row.gallery_shared_at == finished - timedelta(seconds=30)
    detail = await history.get_game_detail(game.game_id, requesting_user_id=ann.id)
    assert detail.turns[0].shares == [game.reactor_seat]
    assert not detail.turns[0].gallery_withdrawn


@pytest.mark.parametrize("visibility", ["private"])
async def test_the_fold_refuses_a_share_the_room_should_have_refused(repos, visibility):
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    with pytest.raises(ValueError, match="Only the drawer"):
        await record_game(
            history, drawer=ann.id, reactor=bob.id, visibility=visibility,
            shared_by="reactor",
        )


async def test_the_fold_skips_a_blank_drawing_and_keeps_the_withdrawal(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    blank = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by="drawer", stroke_count=0,
    )
    assert (await _drawing(factory, blank.turn_id)).gallery_shared_at is None
    assert await _gallery_ids(history) == []


async def test_the_fold_leaves_a_notice_only_where_the_drawer_was_gone(repos):
    """`notify_drawer` is the room's call - whether the drawer was still there
    at the end; the write keeps one notice per drawing, never for the
    drawer's own share."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    watched = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by="reactor",
    )
    gone = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by=("drawer", "reactor"), notify_drawer=True,
    )
    assert await _notices(factory) == [(UUID(ann.id), UUID(gone.turn_id))]
    assert watched.turn_id != gone.turn_id


async def test_taking_the_last_share_back_and_sharing_again_is_not_new(repos):
    """R-SHARE-05: pressing twice must not bump a drawing to the top of New,
    or back into Hot's horizon and This week."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    old = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by="reactor",
        finished_at=NOW - timedelta(days=20),
    )
    recent = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by="reactor",
        finished_at=NOW - timedelta(hours=1),
    )
    first = (await _drawing(factory, old.turn_id)).gallery_shared_at
    for who in (bob, ann):
        await history.set_drawing_share(
            old.game_id, old.turn_id, requesting_user_id=who.id, shared=False
        )
        assert old.turn_id not in await _gallery_ids(history)
        await history.set_drawing_share(
            old.game_id, old.turn_id, requesting_user_id=ann.id, shared=True
        )
        assert await _gallery_ids(history) == [recent.turn_id, old.turn_id]
        assert (await _drawing(factory, old.turn_id)).gallery_shared_at == first
    hot = [entry.turn_id for entry in (await history.list_gallery(sort="hot")).entries]
    assert old.turn_id not in hot, "twenty days old is past Hot's horizon still"


async def test_the_notice_names_the_sharer_still_standing(repos):
    """R-SHARE-09: never somebody who took their share back."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    cid = await registered(users, "Cid")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public",
        shared_by=("drawer", "reactor"), notify_drawer=True,
    )
    assert await _told(factory, ann.id) == [(game.turn_id, "Reactor")]
    await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=bob.id, shared=False
    )
    assert await _told(factory, ann.id) == [(game.turn_id, None)], "the drawer's own share names nobody"
    assert cid  # a third player who never sat in it cannot be named


async def test_a_purged_guest_leaves_their_share_standing(repos):
    """The retention purge removes a guest's row, not the history it made: the
    share stays, credited to the seat's frozen name (SET NULL, not CASCADE)."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    guest = await users.create_anonymous(display_name="Guest")
    game = await record_game(
        history, drawer=ann.id, reactor=guest.id, reactor_is_anonymous=True,
        visibility="public", shared_by="reactor",
    )
    from app.db.models import User

    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == UUID(guest.id)))
        await session.commit()
    async with factory() as session:
        [share] = (await session.scalars(select(TurnDrawingShare))).all()
    assert share.user_id is None
    entry = await history.get_gallery_entry(game.turn_id)
    assert entry is not None and entry.sharer_display_name == "Reactor"
    async with factory() as session:
        assert (await _drawing_projections_slice(session, None)).mismatches == []


async def test_the_share_state_read_is_what_the_writes_left(repos):
    """What a room's open recap reads back after a write that never passed
    through it (R-SHARE-07): the seats first first, and the withdrawal."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game = await record_game(
        history, drawer=ann.id, reactor=bob.id, visibility="public", shared_by=None
    )
    empty = await history.get_drawing_share_state(game.turn_id)
    assert empty is not None and empty.shares == () and not empty.withdrawn

    await history.set_drawing_share(None, game.turn_id, requesting_user_id=bob.id, shared=False)
    await history.set_profile_pins(requesting_user_id=bob.id, turn_ids=[game.turn_id])
    await history.set_drawing_share(
        game.game_id, game.turn_id, requesting_user_id=ann.id, shared=True
    )
    state = await history.get_drawing_share_state(game.turn_id)
    assert state.shares == (game.reactor_seat, game.drawer_seat), "the pin shared first"

    await history.set_drawing_share(None, game.turn_id, requesting_user_id=ann.id, shared=False)
    state = await history.get_drawing_share_state(game.turn_id)
    assert state.shares == () and state.withdrawn

    assert await history.get_drawing_share_state("not-a-turn") is None
    assert await history.get_drawing_share_state("00000000-0000-0000-0000-000000000000") is None
