"""Which PostgreSQL role may do what, and the check that the web process is not the owner (#896).

`web`, `migration` and `maintenance` used to be three sets of timeouts over one
`DATABASE_URL`, so the process answering anonymous traffic connected as the
owner of every table: it could drop and truncate them, disable the trigger
that makes the score ledger append-only, and rewrite `audit_events`, whose
append-only property was a convention of the code. Three roles instead:

- `sketchy_owner` owns the schema and every table, and is used only by
  `python -m app.db.migrate` (`MIGRATION_DATABASE_URL`);
- `sketchy_app` - the web process and operator commands - reads and writes
  rows and nothing else: no DDL, no `TRUNCATE`, no `TRIGGER`, and only
  `INSERT` and `SELECT` on the two ledgers, `audit_events` and `score_events`;
- `sketchy_monitor` holds `pg_monitor` and reads no table
  (`ops/postgres/init.sql`, #889).

The roles themselves are created once by a superuser (`ops/postgres/init.sql`).
The grants are applied here, by the migration command, after every upgrade:
a table a revision creates is granted in the same transaction that creates
it, so no deploy can leave one the application cannot read. Referential
actions (`ON DELETE SET NULL`, `CASCADE`) run with the table owner's rights,
not the caller's, so deleting an account still clears its references in the
ledgers.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

OWNER_ROLE = "sketchy_owner"
APP_ROLE = "sketchy_app"
MONITOR_ROLE = "sketchy_monitor"

# Append-only by grant, not only by convention: the application may add to
# them and read them, and nothing it runs can rewrite or remove a row.
APPEND_ONLY_TABLES = ("audit_events", "score_events")
ROW_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"


def grant_statements(app_role: str = APP_ROLE) -> tuple[str, ...]:
    """The application role's privileges, as idempotent statements run by the owner."""
    ledgers = ", ".join(APPEND_ONLY_TABLES)
    return (
        f"GRANT USAGE ON SCHEMA public TO {app_role}",
        f"GRANT {ROW_PRIVILEGES} ON ALL TABLES IN SCHEMA public TO {app_role}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app_role}",
        # Whatever a later revision creates is granted the same way, even by
        # a hand-run migration that forgot this module.
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT {ROW_PRIVILEGES} ON TABLES TO {app_role}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {app_role}",
        f"REVOKE UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES ON {ledgers} FROM {app_role}",
        # The revision check reads it; only the migration writes it.
        f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM {app_role}",
    )


async def apply_grants(connection: AsyncConnection, *, app_role: str = APP_ROLE) -> bool:
    """Grant the application role its privileges, if the role exists.

    A development or CI database with one role has nobody to grant to, and
    the call is then a no-op. Returns whether anything was granted.
    """
    if connection.dialect.name != "postgresql":
        return False
    exists = await connection.scalar(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": app_role}
    )
    if not exists:
        return False
    for statement in grant_statements(app_role):
        await connection.execute(text(statement))
    return True


async def web_role_privilege_problem(connection: AsyncConnection) -> str | None:
    """Why this connection's role is too powerful to serve traffic, or None.

    One query: a superuser, a role that may create objects in the schema, or
    one that owns any table in it can alter or drop what the application
    only needs to read and write. Production refuses to start on any of them.
    """
    if connection.dialect.name != "postgresql":
        return None
    row = (
        await connection.execute(
            text(
                "SELECT current_user, "
                "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
                "has_schema_privilege(current_user, current_schema(), 'CREATE'), "
                "EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = current_schema() "
                "AND tableowner = current_user)"
            )
        )
    ).one()
    user, superuser, can_create, owns_tables = row
    if superuser:
        return f"the web connection's role {user!r} is a superuser"
    if owns_tables:
        return f"the web connection's role {user!r} owns the schema's tables"
    if can_create:
        return f"the web connection's role {user!r} can create objects in the schema"
    return None
