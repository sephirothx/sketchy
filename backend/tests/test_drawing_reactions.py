"""Reactions to drawings (#520): the rows, the finished-game fold, later writes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_db_engine
from app.db.models import (
    Base,
    GameParticipant,
    GameRecord,
    TurnDrawing,
    TurnDrawingReaction,
    TurnRecord,
    UserStatsDaily,
    generate_uuid,
)
from app.domain_values import (
    OFFERED_REACTION_EMOJI_CODES,
    REACTION_EMOJI_CODES,
    REACTION_SET_VERSION,
    RETIRED_REACTION_EMOJI_CODES,
    TurnDrawingStatus,
)
from app.repositories import sqlalchemy as repo_module
from app.repositories.interfaces import (
    GameHistoryConflictError,
    GameParticipantInput,
    GameRecordInput,
    TurnDrawingInput,
    TurnDrawingReactionInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)
from app.services.user_stats_projection import rebuild_user_stats_projection
from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio

FINISHED_AT = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _skch() -> bytes:
    fixtures = json.loads(
        (Path(__file__).parents[2] / "fixtures" / "canvas_protocol_v1.json").read_text()
    )
    entry = next(
        item for item in fixtures["histories"] if item["name"] == "representative"
    )
    return bytes.fromhex(entry["binary"])


SKCH = _skch()


async def registered(users, name: str):
    guest = await users.create_anonymous(display_name=name)
    return await users.claim_account(guest.id, name.lower(), "hashed")


class Recorded:
    """Ids handed back by `record_game`, so tests can address what was written."""

    def __init__(self, game_id, turn_id, drawer_seat, reactor_seat, drawer, reactor):
        self.game_id = game_id
        self.turn_id = turn_id
        self.drawer_seat = drawer_seat
        self.reactor_seat = reactor_seat
        self.drawer = drawer
        self.reactor = reactor


async def record_game(
    history,
    *,
    drawer,
    reactor,
    reactions=None,
    drawing=True,
    reactor_is_anonymous=False,
    finished_at=FINISHED_AT,
    game_id=None,
) -> Recorded:
    drawer_seat = str(generate_uuid())
    reactor_seat = str(generate_uuid())
    turn_id = str(generate_uuid())
    if reactions is None:
        reactions = []
    elif reactions == "default":
        reactions = [
            TurnDrawingReactionInput(
                turn_id=turn_id,
                seat_id=reactor_seat,
                user_id=reactor,
                emoji="heart",
                set_version=REACTION_SET_VERSION,
            )
        ]
    else:
        reactions = [
            r(turn_id=turn_id, drawer_seat=drawer_seat, reactor_seat=reactor_seat)
            for r in reactions
        ]
    saved_id = await history.save_game(
        GameRecordInput(
            id=game_id,
            room_name="Reactions room",
            scoring_mode="none",
            hint_mode="none",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=finished_at - timedelta(minutes=5),
            finished_at=finished_at,
        ),
        [
            GameParticipantInput(
                user_id=drawer,
                final_score=0,
                final_rank=1,
                seat_id=drawer_seat,
                display_name="Drawer",
                is_anonymous=False,
            ),
            GameParticipantInput(
                user_id=reactor,
                final_score=0,
                final_rank=1,
                seat_id=reactor_seat,
                display_name="Reactor",
                is_anonymous=reactor_is_anonymous,
            ),
        ],
        [
            TurnRecordInput(
                id=turn_id,
                round_number=1,
                turn_number=1,
                drawer_user_id=drawer,
                drawer_seat_id=drawer_seat,
                prompt="lighthouse",
                duration_seconds=30,
                guesser_count=1,
                participant_outcomes=(
                    TurnParticipantOutcomeInput(
                        seat_id=reactor_seat,
                        user_id=reactor,
                        eligible=True,
                        eligibility_reason="eligible",
                        outcome="no_attempt",
                        terminal_state="active",
                    ),
                ),
            )
        ],
        [],
        None,
        [TurnDrawingInput(turn_id=turn_id, payload=SKCH)] if drawing else None,
        reactions,
    )
    return Recorded(saved_id, turn_id, drawer_seat, reactor_seat, drawer, reactor)


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


# --------------------------------------------------------------- the fold


async def test_live_reactions_are_written_with_the_game_and_credit_the_drawer(repos):
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")

    recorded = await record_game(history, drawer=ann.id, reactor=bob.id, reactions="default")

    detail = await history.get_game_detail(recorded.game_id, requesting_user_id=bob.id)
    assert [(r.seat_id, r.emoji) for r in detail.turns[0].reactions] == [
        (recorded.reactor_seat, "heart")
    ]
    assert detail.my_seat_id == recorded.reactor_seat
    assert (await users.get_stats(ann.id)).reactions_received == 1
    assert (await users.get_stats(bob.id)).reactions_received == 0


@pytest.mark.parametrize(
    "bad, message",
    [
        (
            lambda turn_id, drawer_seat, reactor_seat: TurnDrawingReactionInput(
                str(generate_uuid()), reactor_seat, "REACTOR", "heart", 1
            ),
            "unknown turn_id",
        ),
        (
            lambda turn_id, drawer_seat, reactor_seat: TurnDrawingReactionInput(
                turn_id, str(generate_uuid()), "REACTOR", "heart", 1
            ),
            "unknown seat_id",
        ),
        (
            lambda turn_id, drawer_seat, reactor_seat: TurnDrawingReactionInput(
                turn_id, drawer_seat, "DRAWER", "heart", 1
            ),
            "own drawing",
        ),
        (
            lambda turn_id, drawer_seat, reactor_seat: TurnDrawingReactionInput(
                turn_id, reactor_seat, "REACTOR", "thumbs_down", 1
            ),
            "Unknown reaction emoji",
        ),
        (
            lambda turn_id, drawer_seat, reactor_seat: TurnDrawingReactionInput(
                turn_id, reactor_seat, "DRAWER", "heart", 1
            ),
            "identity disagree",
        ),
    ],
)
async def test_save_game_refuses_a_reaction_with_nothing_truthful_behind_it(
    repos, bad, message
):
    """Checked against the rows being written, like every other child row."""
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")

    def make(turn_id, drawer_seat, reactor_seat):
        reaction = bad(turn_id, drawer_seat, reactor_seat)
        return TurnDrawingReactionInput(
            reaction.turn_id,
            reaction.seat_id,
            {"REACTOR": bob.id, "DRAWER": ann.id}[reaction.user_id],
            reaction.emoji,
            reaction.set_version,
        )

    with pytest.raises(ValueError, match=message):
        await record_game(history, drawer=ann.id, reactor=bob.id, reactions=[make])


async def test_a_guest_seat_cannot_hold_a_reaction_at_write_time(repos):
    users, history, _ = repos
    ann = await registered(users, "Ann")
    guest = await users.create_anonymous(display_name="Guest")

    with pytest.raises(ValueError, match="Guest"):
        await record_game(
            history,
            drawer=ann.id,
            reactor=guest.id,
            reactions="default",
            reactor_is_anonymous=True,
        )


async def test_two_reactions_from_one_seat_on_one_drawing_are_refused(repos):
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")

    def one(turn_id, drawer_seat, reactor_seat):
        return TurnDrawingReactionInput(turn_id, reactor_seat, bob.id, "heart", 1)

    def two(turn_id, drawer_seat, reactor_seat):
        return TurnDrawingReactionInput(turn_id, reactor_seat, bob.id, "fire", 1)

    with pytest.raises(ValueError, match="at most one reaction"):
        await record_game(history, drawer=ann.id, reactor=bob.id, reactions=[one, two])


async def test_a_retry_carrying_different_reactions_is_a_conflict_not_a_success(repos):
    """Reactions are in the payload digest, or a differing retry would quietly
    return the id of a game that does not hold them."""
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    game_id = str(generate_uuid())
    await record_game(history, drawer=ann.id, reactor=bob.id, game_id=game_id)

    with pytest.raises(GameHistoryConflictError):
        await record_game(
            history, drawer=ann.id, reactor=bob.id, reactions="default", game_id=game_id
        )


# ------------------------------------------------------- writes afterwards


async def test_a_reaction_can_be_set_changed_and_taken_back(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    recorded = await record_game(history, drawer=ann.id, reactor=bob.id)

    first = await history.set_drawing_reaction(
        recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji="laugh"
    )
    assert first.seat_id == recorded.reactor_seat
    assert [(r.seat_id, r.emoji) for r in first.reactions] == [
        (recorded.reactor_seat, "laugh")
    ]
    assert (await users.get_stats(ann.id)).reactions_received == 1

    changed = await history.set_drawing_reaction(
        recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji="fire"
    )
    assert [r.emoji for r in changed.reactions] == ["fire"]
    # A change is not a second reaction.
    assert (await users.get_stats(ann.id)).reactions_received == 1
    async with factory() as session:
        rows = (await session.scalars(select(TurnDrawingReaction))).all()
        assert len(rows) == 1 and rows[0].set_version == REACTION_SET_VERSION

    removed = await history.set_drawing_reaction(
        recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji=None
    )
    assert removed.emoji is None and removed.reactions == ()
    assert (await users.get_stats(ann.id)).reactions_received == 0

    # Taking back what is not there is a no-op, not a negative count.
    again = await history.set_drawing_reaction(
        recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji=None
    )
    assert again.reactions == ()
    assert (await users.get_stats(ann.id)).reactions_received == 0


async def test_every_refusal_is_none(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    stranger = await registered(users, "Cid")
    guest = await users.create_anonymous(display_name="Guest")
    recorded = await record_game(history, drawer=ann.id, reactor=bob.id)

    async def attempt(**overrides):
        arguments = {
            "game_id": recorded.game_id,
            "turn_id": recorded.turn_id,
            "requesting_user_id": bob.id,
            "emoji": "heart",
        }
        arguments.update(overrides)
        game_id = arguments.pop("game_id")
        turn_id = arguments.pop("turn_id")
        return await history.set_drawing_reaction(game_id, turn_id, **arguments)

    assert await attempt(requesting_user_id=stranger.id) is None, "not in the game"
    assert await attempt(requesting_user_id=guest.id) is None, "a guest"
    assert await attempt(requesting_user_id=ann.id) is None, "their own drawing"
    assert await attempt(game_id=str(generate_uuid())) is None, "no such game"
    assert await attempt(turn_id=str(generate_uuid())) is None, "no such turn"
    assert await attempt(game_id="not-an-id") is None
    assert await attempt(emoji="thumbs_down") is None, "not in the set"
    assert await attempt(requesting_user_id="") is None
    # Nothing above left a row or a count behind.
    async with factory() as session:
        assert (await session.scalars(select(TurnDrawingReaction))).all() == []
    assert (await users.get_stats(ann.id)).reactions_received == 0


async def test_a_claimed_guest_may_react_to_a_game_they_played_as_a_guest(repos):
    """Registered is what the account is now, not what the seat recorded."""
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await users.create_anonymous(display_name="Bob")
    recorded = await record_game(
        history, drawer=ann.id, reactor=bob.id, reactor_is_anonymous=True
    )
    assert (
        await history.set_drawing_reaction(
            recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji="wow"
        )
        is None
    )

    await users.claim_account(bob.id, "bob", "hashed")

    result = await history.set_drawing_reaction(
        recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji="wow"
    )
    assert result is not None and result.emoji == "wow"


async def test_an_erased_drawing_keeps_no_reactions_and_takes_none(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    recorded = await record_game(history, drawer=ann.id, reactor=bob.id, reactions="default")

    async with factory() as session:
        async with session.begin():
            drawing = await session.get(TurnDrawing, UUID(recorded.turn_id))
            drawing.status = TurnDrawingStatus.DELETED.value
            drawing.payload = None
            drawing.checksum_sha256 = None
            drawing.byte_size = None
            drawing.format_magic = None
            drawing.format_version = None
            await session.execute(delete(TurnDrawingReaction))

    assert (
        await history.set_drawing_reaction(
            recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji="fire"
        )
        is None
    )


async def test_a_retired_code_still_reads_back_but_cannot_be_chosen_again(
    repos, monkeypatch
):
    """The stored-drawing rule (R-HIST-18), applied to a code: retiring one
    changes what is offered, never what an existing row means."""
    users, history, _ = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    recorded = await record_game(history, drawer=ann.id, reactor=bob.id)
    await history.set_drawing_reaction(
        recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji="wow"
    )

    monkeypatch.setattr(
        repo_module,
        "OFFERED_REACTION_EMOJI_CODES",
        tuple(code for code in OFFERED_REACTION_EMOJI_CODES if code != "wow"),
    )

    detail = await history.get_game_detail(recorded.game_id, requesting_user_id=bob.id)
    assert [r.emoji for r in detail.turns[0].reactions] == ["wow"]
    cid = await registered(users, "Cid")
    assert (
        await history.set_drawing_reaction(
            recorded.game_id, recorded.turn_id, requesting_user_id=cid.id, emoji="wow"
        )
        is None
    )


def test_the_offered_set_is_the_stored_set_minus_retirements():
    assert set(OFFERED_REACTION_EMOJI_CODES) <= set(REACTION_EMOJI_CODES)
    assert RETIRED_REACTION_EMOJI_CODES <= set(REACTION_EMOJI_CODES)
    assert set(OFFERED_REACTION_EMOJI_CODES) | RETIRED_REACTION_EMOJI_CODES == set(
        REACTION_EMOJI_CODES
    )
    assert REACTION_EMOJI_CODES == ("heart", "laugh", "wow", "fire"), (
        "codes are frozen: add, never reorder, remove or reuse"
    )


# ------------------------------------------------------------- projection


async def test_a_rebuild_reproduces_reactions_received_exactly(repos):
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    recorded = await record_game(history, drawer=ann.id, reactor=bob.id, reactions="default")
    later = await record_game(
        history,
        drawer=ann.id,
        reactor=bob.id,
        finished_at=FINISHED_AT + timedelta(days=1),
    )
    await history.set_drawing_reaction(
        later.game_id, later.turn_id, requesting_user_id=bob.id, emoji="fire"
    )
    expected = await users.get_stats(ann.id)
    assert expected.reactions_received == 2

    async with factory() as session:
        async with session.begin():
            await session.execute(delete(UserStatsDaily))
    await rebuild_user_stats_projection(factory)

    assert await users.get_stats(ann.id) == expected
    async with factory() as session:
        rows = (
            await session.scalars(
                select(UserStatsDaily)
                .where(UserStatsDaily.user_id == UUID(ann.id))
                .order_by(UserStatsDaily.stat_date)
            )
        ).all()
        # One per game day: the reaction given later still lands on its game's day.
        assert [row.reactions_received for row in rows] == [1, 1]
    del recorded


async def test_taking_a_reaction_back_from_an_erased_projection_row_stays_at_zero(repos):
    """The projection is disposable; undoing a count it no longer holds must
    not fail the write or drive the row negative."""
    users, history, factory = repos
    ann = await registered(users, "Ann")
    bob = await registered(users, "Bob")
    recorded = await record_game(history, drawer=ann.id, reactor=bob.id, reactions="default")
    async with factory() as session:
        async with session.begin():
            await session.execute(delete(UserStatsDaily))

    result = await history.set_drawing_reaction(
        recorded.game_id, recorded.turn_id, requesting_user_id=bob.id, emoji=None
    )

    assert result is not None and result.reactions == ()
    assert (await users.get_stats(ann.id)).reactions_received == 0


# ------------------------------------------------------------------ schema


async def test_the_table_refuses_what_the_rules_forbid(tmp_path):
    """Unknown code, second reaction from one seat, a seat from another game,
    and a negative received count - all refused by the database itself."""
    engine = create_db_engine(f"sqlite+aiosqlite:///{tmp_path / 'reactions.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)

    def game_row(gid):
        return GameRecord(
            id=gid,
            room_name="Rules",
            scoring_mode="default",
            hint_mode="none",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=now,
            finished_at=now,
        )

    game_a, game_b = generate_uuid(), generate_uuid()
    drawer_a, reactor_a, seat_b = generate_uuid(), generate_uuid(), generate_uuid()
    turn_a, turn_b = generate_uuid(), generate_uuid()

    def reaction(**overrides):
        values = {
            "game_id": game_a,
            "turn_id": turn_a,
            "participant_id": reactor_a,
            "emoji": "heart",
            "set_version": 1,
        }
        values.update(overrides)
        return TurnDrawingReaction(**values)

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all([game_row(game_a), game_row(game_b)])
                for gid, sid in ((game_a, drawer_a), (game_a, reactor_a), (game_b, seat_b)):
                    session.add(GameParticipant(id=sid, game_id=gid, final_score=0, final_rank=1))
                for gid, tid, drawer in ((game_a, turn_a, drawer_a), (game_b, turn_b, seat_b)):
                    session.add(
                        TurnRecord(
                            id=tid,
                            game_id=gid,
                            round_number=1,
                            turn_number=1,
                            drawer_participant_id=drawer,
                            prompt="anchor",
                            duration_seconds=10,
                        )
                    )
                session.add(reaction())

        for invalid in (
            reaction(emoji="thumbs_down"),
            reaction(emoji="fire"),  # the same seat, again
            reaction(participant_id=seat_b),  # a seat from game B
            reaction(turn_id=turn_b),  # a turn from game B
            reaction(participant_id=drawer_a, set_version=0),
        ):
            with pytest.raises(IntegrityError):
                async with factory() as session:
                    async with session.begin():
                        session.add(invalid)

        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    session.add(
                        UserStatsDaily(
                            user_id=generate_uuid(),
                            stat_date=now.date(),
                            reactions_received=-1,
                        )
                    )
    finally:
        await engine.dispose()
