"""What Solo's tests (#1434) build on: prompt concepts, public games, players.

A recorded game here is the smallest one Solo would serve from: a public
two-or-more seat game with one curated turn, a kept drawing, and somebody
who guessed it. Every keyword turns one of those off, so a test of an
exclusion changes exactly the thing it is about.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.db.models import PromptConcept, PromptVersion, UserSettings, generate_uuid
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    TurnDrawingInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from tests.test_drawing_reactions import SKCH

FINISHED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@dataclass
class Concept:
    id: UUID
    versions: dict[str, UUID] = field(default_factory=dict)


async def seed_concept(
    factory,
    forms: dict[str, str | tuple[str, ...]],
    *,
    rating: str = "everyone",
    state: str = "active",
) -> Concept:
    """One concept with a version per language: `{"en": "lighthouse"}`, or
    `{"en": ("dog", "puppy")}` for an answer with aliases (aliases are not
    stored here; the tests that need them build them themselves)."""
    concept = Concept(id=generate_uuid())
    async with factory() as session:
        async with session.begin():
            session.add(PromptConcept(id=concept.id))
            await session.flush()
            for language, answer in forms.items():
                text = answer if isinstance(answer, str) else answer[0]
                version_id = generate_uuid()
                session.add(
                    PromptVersion(
                        id=version_id,
                        concept_id=concept.id,
                        language=language,
                        version=1,
                        canonical_answer=text,
                        match_key=text.lower().replace(" ", ""),
                        content_rating=rating,
                        moderation_state=state,
                    )
                )
                concept.versions[language] = version_id
    return concept


async def player(users, factory, name: str, *, languages: tuple[str, ...] = ("en",)):
    """A registered player with play languages, default first."""
    guest = await users.create_anonymous(display_name=name)
    account = await users.claim_account(guest.id, name.lower(), "hashed")
    async with factory() as session:
        async with session.begin():
            row = await session.get(UserSettings, UUID(account.id))
            if row is None:
                row = UserSettings(user_id=UUID(account.id))
                session.add(row)
            row.prompt_language = languages[0]
            row.extra_prompt_languages = list(languages[1:])
    return account


@dataclass
class RecordedTurn:
    game_id: str
    turn_id: str
    drawer_seat: str
    guesser_seats: list[str]


async def record_turn(
    history,
    *,
    drawer: str | None,
    guessers: list[str | None],
    version_id: UUID | None,
    visibility: str = "public",
    stroke_count: int = 12,
    correct: int = 1,
    drawing: bool = True,
    finished_at: datetime = FINISHED_AT,
    outcome: str = "finished",
) -> RecordedTurn:
    """One game, one turn: `drawer` draws `version_id`'s answer (a custom
    prompt when it is None), and the first `correct` of `guessers` name it."""
    drawer_seat = str(generate_uuid())
    guesser_seats = [str(generate_uuid()) for _ in guessers]
    turn_id = str(generate_uuid())
    outcomes = tuple(
        TurnParticipantOutcomeInput(
            seat_id=seat,
            user_id=user,
            eligible=True,
            eligibility_reason="eligible",
            outcome="correct" if index < correct else "incorrect",
            terminal_state="active",
            correct_guess_time_seconds=10.0 if index < correct else None,
            points_awarded=0 if index < correct else None,
        )
        for index, (seat, user) in enumerate(zip(guesser_seats, guessers, strict=True))
    )
    game_id = await history.save_game(
        GameRecordInput(
            room_name="Solo source",
            scoring_mode="none",
            hint_mode="none",
            drawing_seconds=80,
            total_rounds=1,
            player_count=1 + len(guessers),
            started_at=finished_at - timedelta(minutes=5),
            finished_at=finished_at,
            visibility=visibility,
            outcome=outcome,
        ),
        [
            GameParticipantInput(
                user_id=drawer, final_score=0, final_rank=1, seat_id=drawer_seat,
                display_name="Drawer", is_anonymous=False,
            ),
            *(
                GameParticipantInput(
                    user_id=user, final_score=0, final_rank=1, seat_id=seat,
                    display_name=f"Guesser {index}", is_anonymous=user is None,
                )
                for index, (seat, user) in enumerate(zip(guesser_seats, guessers, strict=True))
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
                prompt_version_id=str(version_id) if version_id else None,
                prompt_source_kind="curated" if version_id else "custom",
                duration_seconds=30,
                guesser_count=len(guessers),
                stroke_count=stroke_count,
                participant_outcomes=outcomes,
            )
        ],
        None,
        [TurnDrawingInput(turn_id=turn_id, payload=SKCH)] if drawing else None,
    )
    return RecordedTurn(game_id, turn_id, drawer_seat, guesser_seats)
