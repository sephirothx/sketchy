"""Guest-to-account aliasing without destructive history rewrites."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.db.models import (
    AuditEvent,
    IdentityAlias,
    User,
    UserStatsDaily,
    generate_uuid,
)
from app.domain_values import AccountState
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db


async def test_merge_preserves_distinct_historical_seats_and_combines_reads():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        account_guest = await users.create_anonymous("Account")
        account = await users.claim_account(account_guest.id, "Account", "hash")
        guest = await users.create_anonymous("RoadPlayer")
        first_turn = str(generate_uuid())
        second_turn = str(generate_uuid())
        account_seat = str(generate_uuid())
        guest_seat = str(generate_uuid())
        started = datetime(2026, 8, 1, tzinfo=timezone.utc)
        game_id = await history.save_game(
            GameRecordInput(
                room_name="Alias test",
                scoring_mode="default",
                hint_mode="none",
                drawing_seconds=60,
                total_rounds=1,
                player_count=2,
                started_at=started,
                finished_at=started + timedelta(minutes=5),
            ),
            [
                GameParticipantInput(
                    user_id=account.id,
                    final_score=100,
                    final_rank=2,
                    seat_id=account_seat,
                    display_name="Account",
                ),
                GameParticipantInput(
                    user_id=guest.id,
                    final_score=300,
                    final_rank=1,
                    seat_id=guest_seat,
                    display_name="RoadPlayer",
                ),
            ],
            [
                TurnRecordInput(
                    id=first_turn,
                    round_number=1,
                    turn_number=1,
                    drawer_user_id=guest.id,
                    drawer_seat_id=guest_seat,
                    prompt="bridge",
                    duration_seconds=20,
                    guesser_count=1,
                    participant_outcomes=(
                        TurnParticipantOutcomeInput(
                            seat_id=account_seat,
                            user_id=account.id,
                            eligible=True,
                            eligibility_reason="eligible",
                            outcome="correct",
                            terminal_state="active",
                            correct_guess_time_seconds=10,
                            points_awarded=100,
                        ),
                    ),
                ),
                TurnRecordInput(
                    id=second_turn,
                    round_number=1,
                    turn_number=2,
                    drawer_user_id=account.id,
                    drawer_seat_id=account_seat,
                    prompt="tower",
                    duration_seconds=25,
                    guesser_count=1,
                    participant_outcomes=(
                        TurnParticipantOutcomeInput(
                            seat_id=guest_seat,
                            user_id=guest.id,
                            eligible=True,
                            eligibility_reason="eligible",
                            outcome="no_attempt",
                            terminal_state="active",
                        ),
                    ),
                ),
            ],
        )

        merged = await users.merge_guest_into_account(guest.id, account.id)
        assert merged.id == account.id
        assert (await users.get_by_id(guest.id)).id == account.id

        games = (await history.get_user_games(account.id, requesting_user_id=account.id)).games
        assert len(games) == 1
        assert {seat.user_id for seat in games[0].participants} == {
            account.id,
            guest.id,
        }
        assert await history.get_game_detail(
            game_id, requesting_user_id=account.id
        ) is not None

        stats = await users.get_stats(account.id)
        assert stats.games_played == 1
        assert stats.games_won == 1
        assert stats.total_score == 400
        assert stats.average_score == 400
        assert stats.turns_played == 2
        assert stats.drawings_made == 2
        assert stats.prompts_guessed == 1

        async with factory() as session:
            source = await session.get(User, UUID(guest.id))
            alias = await session.scalar(select(IdentityAlias))
            event = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.event_type == "identity.guest_merged"
                )
            )
            assert source is not None and source.state == AccountState.MERGED.value
            assert alias is not None
            assert str(alias.source_user_id) == guest.id
            assert str(alias.target_user_id) == account.id
            assert event is not None
            projection_rows = (
                await session.scalars(select(UserStatsDaily))
            ).all()
            assert len(projection_rows) == 1
            assert projection_rows[0].user_id == UUID(account.id)
            assert projection_rows[0].games_played == 1

        # Retrying the same request is idempotent and does not create a chain.
        assert (await users.merge_guest_into_account(guest.id, account.id)).id == account.id
    finally:
        await engine.dispose()


async def test_a_merged_account_pages_one_history_across_its_identities():
    """A guest's seats keep the guest's id after a merge, so the history is
    one index walk per identity, merged (#477). Paged one game at a time it
    has to interleave the two, list a game both sat in once, and end - and
    show each viewer what #469 lets them see: the owner every game, a visitor
    the public ones, a signed-in stranger those plus the private game they
    sat in with the guest identity (walked down the stranger's own seats)."""
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    try:
        account_guest = await users.create_anonymous("Account")
        account = await users.claim_account(account_guest.id, "Account", "hash")
        guest = await users.create_anonymous("RoadPlayer")
        stranger = await users.create_anonymous("Stranger")
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)

        async def play(index: int, *players: str, visibility: str = "public") -> str:
            finished = start + timedelta(minutes=10 * index)
            return await history.save_game(
                GameRecordInput(
                    room_name=f"Walk {index}",
                    scoring_mode="default",
                    hint_mode="none",
                    drawing_seconds=60,
                    total_rounds=1,
                    player_count=len(players),
                    started_at=finished - timedelta(minutes=5),
                    finished_at=finished,
                    visibility=visibility,
                ),
                [
                    GameParticipantInput(
                        user_id=player,
                        final_score=0,
                        final_rank=1,
                        seat_id=str(generate_uuid()),
                        display_name="Seat",
                    )
                    for player in players
                ],
                [],
            )

        played = [
            await play(
                index,
                account.id if index % 2 == 0 else guest.id,
                visibility="private" if index % 3 == 0 else "public",
            )
            for index in range(6)
        ]
        played.append(await play(6, account.id, guest.id))
        shared = await play(7, guest.id, stranger.id, visibility="private")
        played.append(shared)
        # The stranger's own private game, without the subject: on nobody's
        # view of this profile, though the stranger's walk passes it.
        await play(8, stranger.id, visibility="private")
        public = [played[index] for index in (1, 2, 4, 5, 6)]
        await users.merge_guest_into_account(guest.id, account.id)

        for viewer, expected in (
            (account.id, played),
            (None, public),
            (stranger.id, [*public, shared]),
        ):
            paged, cursor = [], None
            while True:
                page = await history.get_user_games(
                    account.id, limit=2, cursor=cursor, requesting_user_id=viewer
                )
                paged.extend(game.id for game in page.games)
                cursor = page.next_cursor
                if cursor is None:
                    break
            assert paged == expected[::-1], viewer
    finally:
        await engine.dispose()
