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
            # Workers have exited by now. FORCE also clears a connection left
            # by a crashed worker, but only one the dropping role may end: a
            # session of the application role that is still closing when this
            # runs made the owner's DROP fail with "permission denied to
            # terminate process" after a green run. So that role ends its own
            # sessions first - any role may end its own.
            for name in self.names[:]:
                await self._end_role_sessions(name)
                await connection.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
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
