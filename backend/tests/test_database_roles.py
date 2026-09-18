"""The web process connects as a role that cannot alter the schema or rewrite the ledgers (#896)."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import DatabaseRoleError, get_migration_database_url, verify_least_privilege
from app.db.roles import APPEND_ONLY_TABLES, grant_statements

from tests.dbfixtures import create_test_db, create_test_engine

AS_APPLICATION = bool(os.environ.get("TEST_OWNER_DATABASE_URL"))


def test_the_grants_leave_the_ledgers_append_only_and_no_ddl():
    statements = grant_statements("sketchy_app")
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sketchy_app" in statements
    revoke = next(statement for statement in statements if statement.startswith("REVOKE UPDATE, DELETE"))
    assert all(table in revoke for table in APPEND_ONLY_TABLES)
    assert "TRUNCATE" in revoke and "TRIGGER" in revoke
    assert not any(" CREATE " in f" {statement} " or "ALL PRIVILEGES" in statement for statement in statements)


def test_migrations_use_their_own_url_and_production_insists_on_it():
    development = {"DATABASE_URL": "postgresql://app@db/sketchy"}
    assert get_migration_database_url(development).endswith("app@db/sketchy")
    both = {**development, "MIGRATION_DATABASE_URL": "postgresql://owner@db/sketchy"}
    assert "owner@db" in get_migration_database_url(both)
    with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL is required"):
        get_migration_database_url({**development, "SKETCHY_ENV": "production"})
    assert "owner@db" in get_migration_database_url({**both, "SKETCHY_ENV": "production"})


@pytest.mark.skipif(not AS_APPLICATION, reason="needs the suite running as the application role")
async def test_the_application_role_cannot_truncate_alter_or_rewrite_the_ledgers():
    factory, engine = await create_test_db()
    try:
        forbidden = (
            "TRUNCATE users CASCADE",
            "ALTER TABLE users ADD COLUMN sneaky int",
            "CREATE TABLE sneaky (i int)",
            "UPDATE audit_events SET event_type = event_type",
            "DELETE FROM audit_events",
            "UPDATE score_events SET points_delta = points_delta",
            "DELETE FROM score_events",
            "ALTER TABLE score_events DISABLE TRIGGER USER",
            "DELETE FROM alembic_version",
        )
        for statement in forbidden:
            async with engine.connect() as connection:
                with pytest.raises(DBAPIError, match="permission denied|must be owner"):
                    await connection.execute(text(statement))
        # And it can still do what it is for.
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO audit_events (id, event_type, details) VALUES (gen_random_uuid(), 'probe', '{}')")
            )
            assert await connection.scalar(text("SELECT count(*) FROM audit_events")) >= 1
        await verify_least_privilege(engine)
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="the privilege check is PostgreSQL's",
)
async def test_production_refuses_to_serve_as_the_schema_owner():
    owner_url = os.environ.get("TEST_OWNER_DATABASE_URL") or os.environ["TEST_DATABASE_URL"]
    owner = create_test_engine(owner_url)
    try:
        with pytest.raises(DatabaseRoleError, match="owns the schema's tables|superuser"):
            await verify_least_privilege(owner)
    finally:
        await owner.dispose()
