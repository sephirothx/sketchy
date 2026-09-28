"""What authorizing a room's prompt-list selection costs the event loop (#1237).

`authorize_selection` runs when a room is created, when its host changes the
lists, and before every game starts. It checks that no answer or alias reaches
two different prompts under the room's fold, and in a mixed-language room it
asks that of every room language. Seeds one account with ``--lists`` lists of
``--prompts`` prompts and ``--aliases`` aliases each, in ``--language`` (``zxx``,
language-agnostic, is the case a mixed room folds seven times), then authorizes
the whole selection twice: cold, and again unchanged.

For each: the statements issued, process CPU, wall time, and the worst wait a
1 ms ticker saw on the loop meanwhile.

    TEST_DATABASE_URL=postgresql+asyncpg://sketchy:sketchy@127.0.0.1:5433/sketchy_test \\
      backend/.venv/bin/python benchmarks/authorize_selection.py --lists 20 --language zxx --room mixed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import insert  # noqa: E402

from app.db.models import User, generate_uuid  # noqa: E402
from app.domain_values import MIXED_PROMPT_LANGUAGE  # noqa: E402
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository  # noqa: E402
from owned_list_io import Probe, entries  # noqa: E402
from tests.dbfixtures import create_test_db  # noqa: E402


async def run(args) -> dict:
    factory, engine = await create_test_db()
    probe = Probe(engine)
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        user_id = generate_uuid()
        async with factory() as session, session.begin():
            await session.execute(insert(User), [{
                "id": user_id, "display_name": "Host", "username": "Host",
                "password_hash": "hash", "state": "registered",
            }])
        owner = str(user_id)
        slugs = []
        for index in range(args.lists):
            created = await repo.create_owned(
                owner, name=f"List {index}", description="", language=args.language,
                prompts=entries(args.prompts, args.aliases, salt=f"l{index}x"),
            )
            slugs.append(created.slug)
        room = MIXED_PROMPT_LANGUAGE if args.room == "mixed" else args.room

        def authorize():
            return repo.authorize_selection(slugs, requesting_user_id=owner, expected_language=room)

        cold_selection, cold = await probe.measure(authorize())
        _, warm = await probe.measure(authorize())
        return {
            "selection": f"{args.lists} lists x {args.prompts} prompts x {args.aliases} aliases, {args.language}, room {args.room}",
            "prompt_count": cold_selection.prompt_count,
            "cold": cold,
            "warm": warm,
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lists", type=int, default=20)
    parser.add_argument("--prompts", type=int, default=500)
    parser.add_argument("--aliases", type=int, default=20)
    parser.add_argument("--language", default="zxx")
    parser.add_argument("--room", default="mixed", help="`mixed`, or a room language such as en")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
