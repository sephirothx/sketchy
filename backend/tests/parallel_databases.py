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
    def __init__(self, template_url: str):
        # Validate the source before adding a test-looking name to anything.
        assert_disposable(template_url)
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

    async def close(self) -> None:
        if not self.names:
            return
        connection = await asyncpg.connect(
            self.admin_url.render_as_string(hide_password=False)
        )
        try:
            # Workers have exited by now. FORCE also clears a connection left
            # by a crashed worker, but only in databases this controller owns.
            for name in self.names[:]:
                await connection.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
                self.names.remove(name)
        finally:
            await connection.close()
