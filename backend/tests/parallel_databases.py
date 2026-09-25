"""Own only the disposable PostgreSQL clones created for one pytest run.

Each worker needs a whole migrated database: sharing tables lets one fixture
delete another test's rows, and sharing a transaction would stop testing real
commits and READ COMMITTED interleavings. No application engine is shared
across pytest event loops. The controller creates and drops the clones.
"""
from __future__ import annotations

from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url

from tests.dbfixtures import assert_disposable


class WorkerDatabases:
    def __init__(self, template_url: str, role_url: str | None = None):
        # Validate the source before adding a test-looking name to anything.
        assert_disposable(template_url)
        # The role the tests connect as, when it is not the one that owns the
        # clones (#896): its sessions are the ones the owner cannot end.
        self.role_url = role_url
        self.template = make_url(template_url)
        if self.template.get_backend_name() != "postgresql":
            raise ValueError("parallel TEST_DATABASE_URL must use PostgreSQL")
        self.admin_url = self.template.set(drivername="postgresql", database="postgres")
        self.names: list[str] = []

    async def create(self) -> str:
        name = f"sketchy_test_{uuid4().hex}"
        connection = await asyncpg.connect(
            self.admin_url.render_as_string(hide_password=False)
        )
        try:
            # Identifiers cannot be bind parameters. The source may contain
            # quotes; the generated destination contains only ASCII and '_'.
            source = self.template.database.replace('"', '""')
            await connection.execute(f'CREATE DATABASE "{name}" TEMPLATE "{source}"')
            self.names.append(name)
        finally:
            await connection.close()
        return self.template.set(database=name).render_as_string(hide_password=False)

    @staticmethod
    def as_role(clone_url: str, role_url: str) -> str:
        """The same clone, reached with another role's credentials (#896)."""
        role = make_url(role_url)
        return (
            make_url(clone_url)
            .set(username=role.username, password=role.password)
            .render_as_string(hide_password=False)
        )

    async def close(self) -> None:
        if not self.names:
            return
        connection = await asyncpg.connect(
            self.admin_url.render_as_string(hide_password=False)
        )
        try:
            # Workers have exited by now, but a crashed one may have left a
            # connection, and one still closing is still in the database. The
            # owner may not end the application role's sessions, so that role
            # ends its own first - any role may end its own.
            for name in self.names[:]:
                await self._end_role_sessions(name)
                await drop_database(connection, name)
                self.names.remove(name)
        finally:
            await connection.close()

    async def _end_role_sessions(self, name: str) -> None:
        if self.role_url is None:
            return
        url = make_url(self.as_role(self.template.set(database=name).render_as_string(hide_password=False), self.role_url))
        role = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
        try:
            await role.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE datname = current_database() AND usename = current_user"
                " AND pid <> pg_backend_pid()"
            )
        finally:
            await role.close()


async def drop_database(connection: asyncpg.Connection, name: str) -> None:
    """Drop a test database, whatever autovacuum is doing in it.

    Not `WITH (FORCE)`. Before ending anything, FORCE checks that the dropping
    role may signal every backend in the database, and an autovacuum worker
    belongs to no role: only a superuser or a member of pg_signal_backend may
    end one. A database that has just taken a burst of writes is exactly where
    autovacuum runs, so the owner's DROP failed with "permission denied to
    terminate process" on a green run (PR #1117). A plain DROP cancels
    autovacuum itself and waits up to five seconds for other sessions to
    leave, so this ends the sessions the role may end - its own - and lets
    the DROP wait for them to go. Another role's sessions are the caller's to
    end first (`_end_role_sessions`).
    """
    await connection.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
        " WHERE datname = $1 AND usename = current_user AND pid <> pg_backend_pid()",
        name,
    )
    await connection.execute(f'DROP DATABASE IF EXISTS "{name}"')
