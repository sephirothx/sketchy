"""Physical size of the finished-game tables #548 and #549 proposed to trim.

Seeds a batch of finished games of one shape (8 seats, 24 turns, the 72 correct
guesses an alternating rule yields, two curated sources per offered prompt) through the real writer
into a disposable PostgreSQL database, then reports heap and index bytes
for turn_participant_outcomes (and turn_guesses, on a checkout that still has
it), turn_records and turn_prompt_offer_sources per game, and explains the
join that would derive offer sources from memberships. Runs unchanged before
and after #548, so the two can be compared.

    TEST_DATABASE_URL=postgresql+asyncpg://... backend/.venv/bin/python benchmarks/history_row_footprint.py --games 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from app.db.models import (
    Base,
    generate_uuid,
)
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    PromptListEntryInput,
    PromptOfferInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)

try:  # The guess row exists only before #548.
    from app.repositories.interfaces import TurnGuessInput
except ImportError:
    TurnGuessInput = None
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

SEATS, TURNS, CORRECT = 8, 24, 92
TABLES = (("turn_guesses",) if TurnGuessInput else ()) + ("turn_participant_outcomes", "turn_records", "turn_prompt_offers", "turn_prompt_offer_sources", "score_events", "game_participants")


async def _seed_game(history, players, sources, versions, started):
    seats = [str(generate_uuid()) for _ in players]
    turns, guesses = [], []
    correct_left = CORRECT
    for index in range(TURNS):
        drawer = index % SEATS
        turn_id = str(generate_uuid())
        outcomes = []
        for seat_index, seat in enumerate(seats):
            if seat_index == drawer:
                continue
            correct = correct_left > 0 and (index + seat_index) % 2 == 0
            if correct:
                correct_left -= 1
                if TurnGuessInput:
                    guesses.append(TurnGuessInput(turn_id=turn_id, user_id=players[seat_index], seat_id=seat,
                                                  points_awarded=10, guess_time_seconds=5.0))
            outcome = dict(
                seat_id=seat, user_id=players[seat_index], eligible=True, eligibility_reason="eligible",
                outcome="correct" if correct else "incorrect", terminal_state="active",
                correct_guess_time_seconds=5.0 if correct else None, wrong_guess_count=0 if correct else 1)
            if not TurnGuessInput:
                outcome["points_awarded"] = 10 if correct else None
            outcomes.append(TurnParticipantOutcomeInput(**outcome))
        offers = tuple(
            PromptOfferInput(position, f"prompt {index}-{position}", position == 0, "curated",
                             prompt_version_id=versions[(index * 3 + position) % len(versions)],
                             source_revision_ids=tuple(sources))
            for position in range(3)
        )
        turns.append(TurnRecordInput(id=turn_id, round_number=index // SEATS + 1, turn_number=index + 1,
                                     drawer_user_id=players[drawer], drawer_seat_id=seats[drawer],
                                     prompt=f"prompt {index}-0", duration_seconds=60,
                                     prompt_version_id=versions[(index * 3) % len(versions)],
                                     prompt_source_kind="curated", guesser_count=SEATS - 1,
                                     wrong_guess_count=sum(o.wrong_guess_count for o in outcomes),
                                     prompt_offers=offers, participant_outcomes=tuple(outcomes)))
    participants = [GameParticipantInput(user_id=p, final_score=100, final_rank=i + 1, seat_id=s,
                                         display_name=f"P{i}", is_anonymous=False)
                    for i, (p, s) in enumerate(zip(players, seats, strict=True))]
    return await history.save_game(
        GameRecordInput(room_name="Footprint", scoring_mode="default", hint_mode="none", drawing_seconds=60,
                        total_rounds=3, player_count=SEATS, started_at=started, finished_at=started + timedelta(minutes=20),
                        prompt_source_mode="curated", prompt_source_revision_ids=tuple(sources)),
        participants, turns, *([guesses] if TurnGuessInput else []))


async def run(games: int) -> dict:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    users, lists, history = SqlAlchemyUserRepository(factory), SqlAlchemyPromptListRepository(factory), SqlAlchemyGameHistoryRepository(factory)
    players = []
    for i in range(SEATS):
        u = await users.create_anonymous(f"P{i}")
        await users.claim_account(u.id, f"footprint{i}", "hash")
        players.append(u.id)
    revisions, versions = [], []
    for n in range(2):
        created = await lists.create_owned(players[0], name=f"Source {n}", description="", language="en", visibility="private",
                                           prompts=tuple(PromptListEntryInput(answer=f"answer {n}-{k}") for k in range(80)))
        pinned = await lists.authorize_selection([created.slug], requesting_user_id=players[0])
        revisions.extend(pinned.revision_ids)
        versions.extend(e.prompt_version_id for e in created.prompts)
    started = datetime(2026, 8, 1, tzinfo=timezone.utc)
    for g in range(games):
        await _seed_game(history, players, revisions, versions, started + timedelta(hours=g))
    # Earlier seeds leave dead tuples that pg_relation_size still counts;
    # measure the live rows only.
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for table in TABLES + ("game_records", "users", "prompt_list_revision_items", "game_prompt_sources"):
            await conn.execute(text(f"VACUUM FULL ANALYZE {table}"))
    async with engine.connect() as conn:
        sizes = {}
        for table in TABLES:
            rows = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
            heap = await conn.scalar(text(f"SELECT pg_relation_size('{table}')"))
            idx = await conn.scalar(text(f"SELECT pg_indexes_size('{table}')"))
            sizes[table] = {"rows_per_game": rows / games, "heap_bytes_per_game": heap / games, "index_bytes_per_game": idx / games,
                            "total_bytes_per_game": (heap + idx) / games}
        derived = (await conn.execute(text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            "SELECT o.id, i.revision_id FROM turn_prompt_offers o "
            "JOIN turn_records t ON t.id = o.turn_id "
            "JOIN game_prompt_sources s ON s.game_id = t.game_id "
            "JOIN prompt_list_revision_items i ON i.revision_id = s.prompt_list_revision_id AND i.prompt_version_id = o.prompt_version_id "
            "WHERE t.game_id = (SELECT id FROM game_records LIMIT 1)"))).scalar_one()
        stored = (await conn.execute(text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            "SELECT o.id, os.prompt_list_revision_id FROM turn_prompt_offers o "
            "JOIN turn_records t ON t.id = o.turn_id "
            "JOIN turn_prompt_offer_sources os ON os.offer_id = o.id "
            "WHERE t.game_id = (SELECT id FROM game_records LIMIT 1)"))).scalar_one()
        equal = await conn.scalar(text(
            "SELECT count(*) FROM ("
            "SELECT o.id, i.revision_id FROM turn_prompt_offers o JOIN turn_records t ON t.id = o.turn_id "
            "JOIN game_prompt_sources s ON s.game_id = t.game_id "
            "JOIN prompt_list_revision_items i ON i.revision_id = s.prompt_list_revision_id AND i.prompt_version_id = o.prompt_version_id "
            "EXCEPT SELECT offer_id, prompt_list_revision_id FROM turn_prompt_offer_sources) d"))
    await engine.dispose()
    def plan(p):
        node = (p[0] if isinstance(p, list) else json.loads(p)[0])
        return {"execution_ms": node.get("Execution Time"), "buffers": node["Plan"].get("Shared Hit Blocks")}
    return {"games": games, "shape": {"seats": SEATS, "turns": TURNS, "correct": CORRECT}, "sizes": sizes,
            "derived_offer_sources_plan": plan(derived), "stored_offer_sources_plan": plan(stored),
            "derived_minus_stored_rows": equal}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--games", type=int, default=50)
    args = parser.parse_args()
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        parser.error("TEST_DATABASE_URL must point at a disposable PostgreSQL database")
    print(json.dumps(asyncio.run(run(args.games)), indent=2, default=str))


if __name__ == "__main__":
    main()
