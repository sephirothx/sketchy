"""Taking a seat reads the account once and writes activity once (#980)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import event

from app.db.models import IdentityAlias, UserSettings
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


def _count_statements(engine) -> list[str]:
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    return statements


async def test_the_seat_account_and_its_colour_preference_are_one_statement():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        plain = await users.create_anonymous("Plain")
        careful = await users.create_anonymous("Careful")
        async with factory() as session:
            async with session.begin():
                session.add(UserSettings(user_id=UUID(careful.id), colorblind_safe_colors=True))
        statements = _count_statements(engine)

        account, colorblind = await users.get_seat_account(careful.id)
        assert (account.id, colorblind) == (careful.id, True)
        assert len(statements) == 1

        # No settings row reads as the default, not as "unknown".
        assert (await users.get_seat_account(plain.id))[1] is False
        assert await users.get_seat_account("not-a-uuid") == (None, None)
    finally:
        await engine.dispose()


async def test_a_merged_guest_is_seated_as_the_account_it_became():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        guest = await users.create_anonymous("Guest")
        account = await users.create_anonymous("Account")
        async with factory() as session:
            async with session.begin():
                session.add(IdentityAlias(source_user_id=UUID(guest.id), target_user_id=UUID(account.id)))
        seated, _ = await users.get_seat_account(guest.id)
        assert seated.id == account.id == (await users.get_by_id(guest.id)).id
    finally:
        await engine.dispose()


async def test_recording_activity_is_one_statement():
    """It was a SELECT and then an UPDATE through the ORM, on every seat."""
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        guest = await users.create_anonymous("Player")
        statements = _count_statements(engine)
        touched = await users.touch_last_active(guest.id)
        assert touched is not None and touched.id == guest.id and touched.last_active_at is not None
        assert len(statements) == 1 and statements[0].lstrip().upper().startswith("UPDATE")
        assert await users.touch_last_active("01920000-0000-7000-8000-000000000000") is None
    finally:
        await engine.dispose()
