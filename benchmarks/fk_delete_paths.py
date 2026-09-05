"""What deleting a referenced row costs PostgreSQL, with and without the FK indexes (#551).

Seeds one moderator account that moderated many prompt versions and lists,
issued many warnings and revoked many bans, plus a prompt version that many
revisions, aliases and tags reference, then times the deletes that make the
database walk those references (ON DELETE SET NULL for the actor columns,
RESTRICT for the join tables, reported as a refused delete) and prints the
plan's trigger timings. Run it at the migration before b2c5a9d3e470 and at
head to see the scan become a probe.

    TEST_DATABASE_URL=postgresql+asyncpg://... backend/.venv/bin/python benchmarks/fk_delete_paths.py --rows 20000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from time import perf_counter

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

from sqlalchemy import insert, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import (  # noqa: E402
    PromptConcept,
    PromptList,
    PromptListRevision,
    PromptListRevisionItem,
    PromptVersion,
    User,
    UserWarning,
    generate_uuid,
)


async def _seed(session, rows: int) -> tuple:
    moderator = generate_uuid()
    victim = generate_uuid()
    session.add_all(
        [
            User(id=moderator, display_name="Moderator", username="fkmod", password_hash="x", state="registered", role="moderator"),
            User(id=victim, display_name="Warned"),
        ]
    )
    await session.flush()
    concept_ids = [generate_uuid() for _ in range(rows)]
    await session.execute(insert(PromptConcept), [{"id": cid} for cid in concept_ids])
    version_ids = [generate_uuid() for _ in range(rows)]
    await session.execute(
        insert(PromptVersion),
        [
            {
                "id": vid, "concept_id": cid, "language": "en", "version": 1,
                "canonical_answer": f"answer {i}", "match_key": f"answer {i}",
                "moderated_by_user_id": moderator,
            }
            for i, (vid, cid) in enumerate(zip(version_ids, concept_ids, strict=True))
        ],
    )
    list_id = generate_uuid()
    session.add(PromptList(id=list_id, slug="fk-bench", name="FK bench", is_bundled=True))
    await session.flush()
    revision_ids = [generate_uuid() for _ in range(rows // 50)]
    await session.execute(
        insert(PromptListRevision),
        [
            {"id": rid, "prompt_list_id": list_id, "version": i + 1, "language": "en",
             "content_hash": f"{i:064x}", "letter_counts": {}, "letter_total": 0}
            for i, rid in enumerate(revision_ids)
        ],
    )
    shared_version = version_ids[0]
    await session.execute(
        insert(PromptListRevisionItem),
        [{"revision_id": rid, "prompt_version_id": shared_version, "position": 0} for rid in revision_ids],
    )
    await session.execute(
        insert(UserWarning),
        [
            {"id": generate_uuid(), "user_id": victim, "issued_by_user_id": moderator,
             "reason": "spam", "message": f"warning {i}"}
            for i in range(rows)
        ],
    )
    return moderator, shared_version


async def _explain(session, sql: str, params: dict) -> dict:
    started = perf_counter()
    plan = (await session.execute(text("EXPLAIN (ANALYZE, FORMAT JSON) " + sql), params)).scalar_one()
    elapsed = perf_counter() - started
    root = plan[0] if isinstance(plan, list) else json.loads(plan)[0]
    triggers = root.get("Triggers", [])
    return {
        "seconds": round(elapsed, 4),
        "execution_ms": root.get("Execution Time"),
        "triggers": [
            {"name": t.get("Constraint Name") or t.get("Trigger Name"), "time_ms": t.get("Time"), "calls": t.get("Calls")}
            for t in triggers
        ],
    }


async def run(rows: int) -> dict:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM user_warnings"))
            await session.execute(text("DELETE FROM users WHERE username = 'fkmod' OR display_name LIKE 'Guest %' OR display_name = 'Warned'"))
            await session.execute(text("DELETE FROM prompt_lists WHERE slug = 'fk-bench'"))
            await session.execute(text("DELETE FROM prompt_versions WHERE canonical_answer LIKE 'answer %'"))
            await session.execute(text("DELETE FROM prompt_concepts WHERE id NOT IN (SELECT concept_id FROM prompt_versions)"))
            moderator, shared_version = await _seed(session, rows)
        await session.execute(text("ANALYZE"))
        await session.commit()
    results = {}
    # The case the indexes are for: accounts with no moderation rows of their
    # own (a retention batch of guests) deleted while the child tables are
    # large. Every SET NULL trigger still has to look, and without an index
    # each look is a scan of the whole child table.
    guests = [generate_uuid() for _ in range(500)]
    async with factory() as session:
        async with session.begin():
            await session.execute(
                insert(User), [{"id": gid, "display_name": f"Guest {i}"} for i, gid in enumerate(guests)]
            )
    async with factory() as session:
        async with session.begin():
            results["delete_500_unreferenced_users"] = await _explain(
                session,
                "DELETE FROM users WHERE id = ANY(CAST(:ids AS uuid[]))",
                {"ids": guests},
            )
            await session.rollback()
    async with factory() as session:
        async with session.begin():
            results["delete_moderator_set_null"] = await _explain(
                session, "DELETE FROM users WHERE id = :id", {"id": moderator}
            )
            await session.rollback()
    async with factory() as session:
        async with session.begin():
            try:
                results["delete_shared_version_restrict"] = await _explain(
                    session, "DELETE FROM prompt_versions WHERE id = :id", {"id": shared_version}
                )
            except Exception as error:  # the RESTRICT refuses; the time to refuse is the point
                results["delete_shared_version_restrict"] = {"refused": type(error).__name__}
            await session.rollback()
    async with factory() as session:
        indexes = (
            await session.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename IN "
                    "('prompt_versions','prompt_lists','user_bans','user_warnings',"
                    "'prompt_list_revision_items','prompt_version_aliases',"
                    "'prompt_version_tags','prompt_list_revision_tags') ORDER BY 1"
                )
            )
        ).scalars().all()
    await engine.dispose()
    return {"rows": rows, "indexes": list(indexes), **results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        parser.error("TEST_DATABASE_URL must point at a disposable PostgreSQL database")
    result = asyncio.run(run(args.rows))
    encoded = json.dumps(result, indent=2, default=str)
    print(encoded)
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as output:
            output.write(encoded)


if __name__ == "__main__":
    main()
