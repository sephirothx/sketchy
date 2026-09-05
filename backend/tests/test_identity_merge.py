"""Guest-to-account aliasing without destructive history rewrites."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
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
    TurnGuessInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db


@pytest.mark.asyncio
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
            [
                TurnGuessInput(
                    turn_id=first_turn,
                    user_id=account.id,
                    seat_id=account_seat,
                    points_awarded=100,
                    guess_time_seconds=10,
                )
            ],
        )

        merged = await users.merge_guest_into_account(guest.id, account.id)
        assert merged.id == account.id
        assert (await users.get_by_id(guest.id)).id == account.id

        games = await history.get_user_games(account.id)
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
