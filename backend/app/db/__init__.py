"""Database engine, session management, and lifecycle initialization."""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
import os
import sys
from pathlib import Path
from time import monotonic, perf_counter
from typing import Any
import warnings
import weakref

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from alembic.util.exc import CommandError
from sqlalchemy import event, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SAWarning
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.services.telemetry import (
    PoolGauges,
    Telemetry,
    current_database_operation,
    telemetry,
)

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./sketchy.db"
SQLITE_BUSY_TIMEOUT_MS = 5_000
POSTGRES_POOL_SIZE = 5
POSTGRES_MAX_OVERFLOW = 5
POSTGRES_POOL_TIMEOUT_SECONDS = 10
POSTGRES_POOL_RECYCLE_SECONDS = 1_800
# A pooled connection returned this long ago or more is pinged before it is
# handed out again (#973); one used more recently is not. SQLAlchemy's
# `pool_pre_ping` pinged on *every* checkout, and on asyncpg its ping is
# BEGIN, a statement and ROLLBACK - three round trips before each session's
# own work, when most sessions run one statement. A backend the server ended
# (a restart, `pg_terminate_backend`, an idle-in-transaction timeout) closes
# its socket, which asyncpg has already seen by the next checkout, so that
# case costs a flag read rather than a ping; what only a ping finds is a
# connection whose peer vanished without a word - a dropped NAT entry, a
# failed-over host - and that takes a quiet spell to happen.
POSTGRES_POOL_PING_IDLE_SECONDS = 30
POSTGRES_MIGRATION_LOCK_ID = int.from_bytes(b"SKETCHY", "big")

# Server-enforced budgets for a PostgreSQL connection, by the role the
# process plays (#555). These bound one statement, one lock wait and one
# idle transaction; they do not bound a whole retention run or a
# transaction that keeps issuing statements - the sweeps' own budgets do
# that. The web role is the application; the migration role holds DDL and
# the deploy advisory lock, where waiting long is worse than failing fast;
# the maintenance role is every operator command that reads or rewrites
# history and may legitimately run a long statement.
#   statement_timeout, lock_timeout, idle_in_transaction_session_timeout
POSTGRES_ROLE_BUDGETS: dict[str, tuple[int, int, int]] = {
    "web": (30, 5, 60),
    "migration": (600, 5, 60),
    "maintenance": (600, 5, 120),
}
_ROLE_ENV = {
    "web": ("DB_STATEMENT_TIMEOUT_SECONDS", "DB_LOCK_TIMEOUT_SECONDS", "DB_IDLE_TRANSACTION_TIMEOUT_SECONDS"),
    "migration": (
        "DB_MIGRATION_STATEMENT_TIMEOUT_SECONDS",
        "DB_MIGRATION_LOCK_TIMEOUT_SECONDS",
        "DB_MIGRATION_IDLE_TRANSACTION_TIMEOUT_SECONDS",
    ),
    "maintenance": (
        "DB_MAINTENANCE_STATEMENT_TIMEOUT_SECONDS",
        "DB_MAINTENANCE_LOCK_TIMEOUT_SECONDS",
        "DB_MAINTENANCE_IDLE_TRANSACTION_TIMEOUT_SECONDS",
    ),
}


class DatabaseRevisionError(RuntimeError):
    """Raised when an externally managed database is not at Alembic head."""


def configure_sqlite_connection(dbapi_connection: Any, _: Any) -> None:
    """Apply SQLite integrity and concurrency settings to every connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def get_database_url(raw_url: str | None = None) -> str:
    """Read and normalize the database connection URL from environment.

    An explicit value lets a caller classify a URL it already holds - the
    production guard in `app.deployment` reads an injected environment rather
    than the process one - without normalizing the scheme a second way.
    """
    if raw_url is None:
        raw_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    url = raw_url.strip()
    if not url:
        return DEFAULT_DATABASE_URL

    # Normalize common scheme prefixes to async driver counterparts
    if url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    return url


def get_engine_connect_args(url: str, *, role: str = "web") -> dict[str, Any]:
    """Provide driver-specific engine parameters.

    For PostgreSQL that is the role's `application_name` - what
    `pg_stat_activity` shows - and its server-enforced budgets. asyncpg sends
    `server_settings` on every connection it opens, so a pooled connection
    that was recycled or re-established after a pre-ping failure carries
    them too; nothing has to re-apply them on checkout.
    """
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    if url.startswith("postgresql"):
        return {"server_settings": postgres_server_settings(role)}
    return {}


def postgres_server_settings(role: str = "web") -> dict[str, str]:
    """The role's PostgreSQL session settings, validated from the environment.

    Values are seconds in the environment and milliseconds on the wire.
    Invalid values fail here, at startup, next to the pool settings.
    """
    if role not in POSTGRES_ROLE_BUDGETS:
        raise ValueError(f"unknown database role {role!r}")
    defaults = POSTGRES_ROLE_BUDGETS[role]
    names = _ROLE_ENV[role]
    statement, lock, idle = (
        _integer_setting(name, default, minimum=1)
        for name, default in zip(names, defaults, strict=True)
    )
    return {
        "application_name": f"sketchy-{role}",
        "statement_timeout": str(statement * 1000),
        "lock_timeout": str(lock * 1000),
        "idle_in_transaction_session_timeout": str(idle * 1000),
    }


def _integer_setting(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


class TimedQueuePool(AsyncAdaptedQueuePool):
    """The PostgreSQL pool, timing how long each checkout waited (#892).

    The statement timer starts once a cursor exists, after the checkout, so a
    request that spent three seconds queueing for one of ten connections and
    three milliseconds in the database looked fast; and a checkout that gave
    up raised before any cursor existed, so it was counted nowhere. The wait
    includes opening an overflow connection, which is part of what the
    caller waited for. The store is the process-wide one unless a test sets
    `store` on the class.
    """

    store: Telemetry | None = None

    def _do_get(self):
        target = self.store if self.store is not None else telemetry
        started = perf_counter()
        try:
            connection = super()._do_get()
        except sa_exc.TimeoutError:
            target.db_pool_checkout(perf_counter() - started, timed_out=True)
            raise
        except BaseException:
            target.db_pool_checkout(perf_counter() - started)
            raise
        target.db_pool_checkout(perf_counter() - started)
        return connection


def get_engine_pool_options(url: str) -> dict[str, Any]:
    """Return deliberate production pool limits for PostgreSQL engines."""
    if not url.startswith("postgresql"):
        return {}
    return {
        "poolclass": TimedQueuePool,
        "pool_size": _integer_setting(
            "DB_POOL_SIZE", POSTGRES_POOL_SIZE, minimum=1
        ),
        "max_overflow": _integer_setting(
            "DB_MAX_OVERFLOW", POSTGRES_MAX_OVERFLOW, minimum=0
        ),
        "pool_timeout": _integer_setting(
            "DB_POOL_TIMEOUT_SECONDS", POSTGRES_POOL_TIMEOUT_SECONDS, minimum=1
        ),
        "pool_recycle": _integer_setting(
            "DB_POOL_RECYCLE_SECONDS", POSTGRES_POOL_RECYCLE_SECONDS, minimum=1
        ),
    }


def pool_ping_idle_seconds() -> int:
    """How long a pooled connection may sit unused before it is pinged."""
    return _integer_setting(
        "DB_POOL_PING_IDLE_SECONDS", POSTGRES_POOL_PING_IDLE_SECONDS, minimum=0
    )


_RETURNED_AT = "sketchy_returned_at"

#: Execution options for a read that is one statement (#973).
AUTOCOMMIT = {"isolation_level": "AUTOCOMMIT"}


@asynccontextmanager
async def read_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A session for a read that is a single statement, run outside a transaction.

    On PostgreSQL a session's first statement opens a transaction and closing
    the session ends it: `BEGIN` and `ROLLBACK` around a lone `SELECT` are two
    of its three round trips. One statement is already its own snapshot, so
    under `AUTOCOMMIT` it is one round trip. SQLite is left alone: its
    transaction is a call into the same process, and toggling the setting
    there costs more than it saves.

    Only for one statement. Two statements under this see two snapshots, and
    a write under it commits on its own.
    """
    async with session_factory() as session:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            await session.connection(execution_options=AUTOCOMMIT)
        yield session


def install_idle_ping(engine: AsyncEngine, *, idle_seconds: float, clock=monotonic) -> None:
    """Check a connection on checkout the cheap way, and ping only a quiet one.

    Replaces `pool_pre_ping` (#973). Every checkout asks the driver whether the
    connection is already closed, which is free; a connection unused for
    `idle_seconds` or more is also pinged. Either finding raises
    `DisconnectionError`, on which the pool discards the connection and hands
    out another - the same recovery `pool_pre_ping` used, without its three
    round trips on every busy checkout.
    """
    dialect = engine.sync_engine.dialect

    def stamp(_dbapi_connection, record) -> None:
        record.info[_RETURNED_AT] = clock()

    def check(dbapi_connection, record, _proxy) -> None:
        driver = getattr(dbapi_connection, "driver_connection", None)
        is_closed = getattr(driver, "is_closed", None)
        if is_closed is not None and is_closed():
            raise sa_exc.DisconnectionError("connection closed while pooled")
        returned_at = record.info.get(_RETURNED_AT)
        if returned_at is None or clock() - returned_at < idle_seconds:
            return
        try:
            dialect.do_ping(dbapi_connection)
        except Exception as error:
            raise sa_exc.DisconnectionError("pooled connection failed its ping") from error

    # A fresh connection counts as just returned: it was opened a moment ago.
    event.listen(engine.sync_engine, "connect", stamp)
    event.listen(engine.sync_engine, "checkin", stamp)
    event.listen(engine.sync_engine, "checkout", check)


def pool_gauges(engine: AsyncEngine, *, max_overflow: int | None = None) -> PoolGauges | None:
    """What the pool will say about itself, or `None` for a pool that keeps no count.

    SQLite's pools do not implement the accessors, and asking them raises
    rather than answering zero; `None` is the honest answer there and the
    exposition simply omits the family.
    """
    pool = engine.sync_engine.pool
    try:
        size = int(pool.size())
        checked_in = int(pool.checkedin())
        checked_out = int(pool.checkedout())
        overflow = int(pool.overflow())
    except (AttributeError, NotImplementedError):
        return None
    if max_overflow is None:
        max_overflow = int(getattr(pool, "_max_overflow", 0) or 0)
    return PoolGauges(
        size=size,
        checked_out=checked_out,
        checked_in=checked_in,
        overflow=max(0, overflow),
        capacity=size + max(0, max_overflow),
    )


@dataclass(frozen=True)
class EngineListeners:
    """The three listeners `instrument_engine` attached, so a test can call them."""

    before: Callable[..., None]
    after: Callable[..., None]
    failed: Callable[..., None]


# SQLSTATE → the cause label on `sketchy_db_query_errors_total` (#892). Exact
# codes first, then two-character classes. These are the failures the
# schema's concurrency design is built to make rare - the lock budget and
# ascending lock order against deadlocks, the erasure barrier's retries
# against serialization - so each gets its own count rather than one number.
_SQLSTATE_CAUSES = {
    "57014": "timeout",  # query_canceled: statement_timeout
    "25P03": "timeout",  # idle_in_transaction_session_timeout
    "55P03": "lock_timeout",  # lock_not_available: lock_timeout, NOWAIT
    "40P01": "deadlock",
    "40001": "serialization",
    "53300": "connection",  # too_many_connections
    "57P01": "connection",  # admin_shutdown
    "57P02": "connection",
    "57P03": "connection",
}
_SQLSTATE_CLASS_CAUSES = {"23": "integrity", "08": "connection"}


def classify_database_error(error: BaseException | None, *, is_disconnect: bool = False) -> str:
    """The cause label for a failed statement, from its SQLSTATE where it has one."""
    if is_disconnect:
        return "connection"
    seen: set[int] = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "pgcode", None) or getattr(current, "sqlstate", None)
        if isinstance(code, str) and len(code) == 5:
            return _SQLSTATE_CAUSES.get(code) or _SQLSTATE_CLASS_CAUSES.get(code[:2], "other")
        name = type(current).__name__
        if name == "IntegrityError":
            return "integrity"
        if name == "OperationalError" and "locked" in str(current).lower():
            # SQLite's busy timeout ran out: its lock budget.
            return "lock_timeout"
        if isinstance(current, (ConnectionError, TimeoutError)) or name in (
            "InterfaceError",
            "ConnectionDoesNotExistError",
        ):
            return "connection"
        current = getattr(current, "orig", None) or current.__cause__
    return "other"


def instrument_engine(engine: AsyncEngine, store: Telemetry | None = None) -> EngineListeners:
    """Time every statement the engine runs, on the store given or the default.

    The listeners run inside SQLAlchemy's greenlet on the event-loop thread,
    so they do the least possible: two clock reads and one counter bump.
    For aiosqlite the span includes the hand-off to its worker thread, which
    is exactly the latency the caller feels. Each statement and transaction
    carries the operation named by `database_operation` around it (#892).
    """
    target = store if store is not None else telemetry

    def before(conn, cursor, statement, parameters, context, executemany):
        context._sketchy_started = perf_counter()

    def after(conn, cursor, statement, parameters, context, executemany):
        started = getattr(context, "_sketchy_started", None)
        if started is not None:
            target.db_query(perf_counter() - started)

    def failed(exception_context):
        context = exception_context.execution_context
        started = getattr(context, "_sketchy_started", None)
        if started is not None:
            # Cleared so a retried statement on the same context is not
            # counted twice, and the error is not also counted as a success.
            context._sketchy_started = None
            target.db_query(
                perf_counter() - started,
                failed=True,
                cause=classify_database_error(
                    getattr(exception_context, "original_exception", None),
                    is_disconnect=bool(getattr(exception_context, "is_disconnect", False)),
                ),
            )

    # Keyed by the Connection itself rather than kept in `conn.info`: reading
    # `info` on a connection the server has just terminated tries to
    # reconnect, and a rollback listener must never be what raises.
    open_transactions: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    def began(conn):
        open_transactions[conn] = (perf_counter(), current_database_operation())

    def ended(conn):
        started = open_transactions.pop(conn, None)
        if started is not None:
            target.db_transaction(perf_counter() - started[0], operation=started[1])

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    event.listen(engine.sync_engine, "after_cursor_execute", after)
    event.listen(engine.sync_engine, "handle_error", failed)
    event.listen(engine.sync_engine, "begin", began)
    event.listen(engine.sync_engine, "commit", ended)
    event.listen(engine.sync_engine, "rollback", ended)
    return EngineListeners(before=before, after=after, failed=failed)


def create_db_engine(url: str | None = None, *, role: str = "web") -> AsyncEngine:
    """Create an async SQLAlchemy engine instance for one database role."""
    resolved_url = url or get_database_url()
    pool_options = get_engine_pool_options(resolved_url)
    engine = create_async_engine(
        resolved_url,
        echo=False,
        connect_args=get_engine_connect_args(resolved_url, role=role),
        future=True,
        **pool_options,
    )
    if resolved_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", configure_sqlite_connection)
    if resolved_url.startswith("postgresql"):
        install_idle_ping(engine, idle_seconds=pool_ping_idle_seconds())
    instrument_engine(engine)
    return engine


def data_directory(url: str | None = None) -> str | None:
    """Where the data lives, for the disk gauge: the SQLite file's folder, else here.

    ``None`` on PostgreSQL. The data is on the database host there, and the
    application's working directory says nothing about that volume - a gauge
    reading it would keep ``SketchyDiskLow`` quiet while the database filled.
    The database volume is measured by node_exporter on its own host instead
    (``ops/prometheus/scrape-example.yml``, #889).
    """
    resolved_url = url or get_database_url()
    if not resolved_url.startswith("sqlite"):
        return None
    if ":memory:" not in resolved_url:
        path = resolved_url.split("///", 1)[-1].split("?", 1)[0]
        if path:
            return str(Path(path).expanduser().resolve().parent)
    return os.getcwd()


# Default process-wide engine and session factory
async_engine: AsyncEngine = create_db_engine()
telemetry.sources.pool = lambda: pool_gauges(
    async_engine, max_overflow=get_engine_pool_options(get_database_url()).get("max_overflow")
)
telemetry.process.data_path = data_directory()
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


command_logger = logging.getLogger("app.db.command")


def summarise_on_dispose(engine: AsyncEngine, *, role: str, command: str | None = None) -> None:
    """Log one structured line when an operator engine is disposed (#892).

    An operator command's engine is instrumented like the web one, but
    nothing scrapes a process that lives for a minute, so how long a
    migration or a rebuild took, and how much it did, was recorded nowhere.
    The line carries the command, the role, the seconds from engine creation
    to disposal, the statements sent, the rows they reported and the ones
    that failed - counts only, never a statement's text or a parameter.
    """
    started = perf_counter()
    counts = {"statements": 0, "rows": 0, "errors": 0}

    def after(conn, cursor, statement, parameters, context, executemany):
        counts["statements"] += 1
        rowcount = getattr(cursor, "rowcount", -1)
        if isinstance(rowcount, int) and rowcount > 0:
            counts["rows"] += rowcount

    def failed(exception_context):
        counts["errors"] += 1

    def disposed(_engine):
        if not command_logger.hasHandlers():
            # A command that never configured logging would drop an INFO
            # line on the floor; this is the one line it exists to leave.
            from app.logging_config import configure_logging

            configure_logging()
        name = command or _command_name()
        seconds = round(perf_counter() - started, 3)
        command_logger.info(
            "%s finished in %.3fs: %d statements, %d rows, %d failed",
            name,
            seconds,
            counts["statements"],
            counts["rows"],
            counts["errors"],
            extra={"fields": {"command": name, "role": role, "seconds": seconds, **counts}},
        )

    event.listen(engine.sync_engine, "after_cursor_execute", after)
    event.listen(engine.sync_engine, "handle_error", failed)
    event.listen(engine.sync_engine, "engine_disposed", disposed)


def _command_name() -> str:
    """The module run with `python -m`, which is how every operator command starts."""
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    return getattr(spec, "name", None) or os.path.basename(sys.argv[0] or "python")


def maintenance_engine() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """An engine and session factory for an operator command.

    Separate from the process-wide web engine on purpose: a rebuild, a
    verification pass or an export batch may run statements far longer than
    a request may, and gets the maintenance budgets rather than the web
    ones by accident of sharing the import. Its disposal logs the command's
    one-line summary.
    """
    engine = create_db_engine(role="maintenance")
    summarise_on_dispose(engine, role="maintenance")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, factory


def get_alembic_config(ini_path: Path | None = None) -> AlembicConfig:
    """Construct an Alembic Config object pointing to the repository alembic setup."""
    if ini_path is None:
        ini_path = Path(__file__).resolve().parent.parent.parent / "alembic.ini"
    cfg = AlembicConfig(str(ini_path))
    cfg.attributes["skip_logging_config"] = True
    return cfg


def _run_alembic_upgrade_sync(
    connection: Connection, alembic_cfg: AlembicConfig
) -> None:
    alembic_cfg.attributes["connection"] = connection
    # SQLite cannot reflect the two hand-written expression indexes. The
    # baseline revision and the migration suite pin their exact definition
    # directly, so suppress only this known warning while batch migrations
    # reflect FKs.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*ix_users_(?:username|email)_lower.*",
            category=SAWarning,
        )
        alembic_command.upgrade(alembic_cfg, "head")


def _database_revisions_sync(
    connection: Connection, alembic_cfg: AlembicConfig
) -> tuple[set[str], set[str]]:
    current = set(MigrationContext.configure(connection).get_current_heads())
    script = ScriptDirectory.from_config(alembic_cfg)
    unknown = []
    for revision in sorted(current):
        try:
            script.get_revision(revision)
        except (ResolutionError, CommandError):
            unknown.append(revision)
    if unknown:
        raise DatabaseRevisionError(
            f"Database is at revision {unknown}, which this checkout does not know. "
            "The migration chain that built it was folded into one baseline before "
            "launch (#557), so it cannot be upgraded: it holds development data only. "
            "Delete the SQLite file (or drop and recreate the PostgreSQL database) "
            "and start again."
        )
    return current, set(script.get_heads())


def assert_references_intact(connection: Any) -> None:
    """Refuse to finish a SQLite migration run that broke a reference.

    Migrations run with foreign keys off, because batch mode rebuilds a table
    by copy, drop, rename and DROP TABLE fires ON DELETE CASCADE - so altering
    a table others point at would silently empty them. Enforcement has to be
    off for that not to fail outright, which means nothing complains at the
    moment something goes wrong. This is the complaint, moved to the end.
    """
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            "migration left dangling references: "
            + ", ".join(sorted({str(row[0]) for row in violations}))
        )


async def upgrade_database(engine: AsyncEngine | None = None) -> None:
    """Upgrade to Alembic head, serializing PostgreSQL deploys."""
    target_engine = engine or async_engine
    alembic_cfg = get_alembic_config()

    async with target_engine.begin() as conn:
        if target_engine.dialect.name == "postgresql":
            # A transaction-scoped lock releases automatically on both commit
            # and rollback, including when migration DDL fails.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": POSTGRES_MIGRATION_LOCK_ID},
            )
        # A database at a revision this checkout never heard of is refused
        # with the rebuild instruction, not handed to Alembic to trip over
        # "table already exists" halfway through the baseline.
        await conn.run_sync(_database_revisions_sync, alembic_cfg)
        await conn.run_sync(_run_alembic_upgrade_sync, alembic_cfg)
        # In the same transaction as the tables they cover, so no deploy can
        # leave a table the application role cannot read (#896).
        from app.db.roles import apply_grants

        await apply_grants(conn)


async def verify_database_head(engine: AsyncEngine | None = None) -> None:
    """Fail startup clearly when a managed database has not been migrated."""
    target_engine = engine or async_engine
    alembic_cfg = get_alembic_config()
    async with target_engine.connect() as conn:
        current, expected = await conn.run_sync(_database_revisions_sync, alembic_cfg)
    if current != expected:
        raise DatabaseRevisionError(
            "Database schema is not at Alembic head "
            f"(current: {sorted(current) or ['base']}; expected: {sorted(expected)}). "
            "Run `python -m app.db.migrate` before starting Sketchy."
        )


class DatabaseRoleError(RuntimeError):
    """The web process connected with a role that can alter the schema."""


async def verify_least_privilege(engine: AsyncEngine | None = None) -> None:
    """Refuse to serve from a connection that owns the schema (#896, R-PLAT-22).

    Production only - the caller decides - because development and CI run as
    one role on purpose. One query beside the revision check.
    """
    from app.db.roles import web_role_privilege_problem

    target_engine = engine or async_engine
    async with target_engine.connect() as conn:
        problem = await web_role_privilege_problem(conn)
    if problem is not None:
        raise DatabaseRoleError(
            f"Refusing to start: {problem}. Connect the web process as the application "
            "role (sketchy_app) and migrate with MIGRATION_DATABASE_URL as the owner; "
            "see ops/postgres/init.sql."
        )


def get_migration_database_url(environ: dict[str, str] | None = None) -> str:
    """The URL `python -m app.db.migrate` connects with: the schema owner's (#896).

    `MIGRATION_DATABASE_URL`, falling back to `DATABASE_URL` outside
    production, where one role is the norm. Production refuses the fallback:
    the web role cannot run DDL, so a migration attempted with it would fail
    halfway rather than at the start.
    """
    from app.deployment import is_production

    values = os.environ if environ is None else environ
    raw = (values.get("MIGRATION_DATABASE_URL") or "").strip()
    if raw:
        return get_database_url(raw)
    if is_production(values):
        raise RuntimeError(
            "MIGRATION_DATABASE_URL is required in production: migrations run as the "
            "schema owner, and DATABASE_URL is the application role's."
        )
    return get_database_url(values.get("DATABASE_URL"))


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Prepare zero-config SQLite or verify externally managed databases."""
    target_engine = engine or async_engine
    if target_engine.dialect.name == "sqlite":
        await upgrade_database(target_engine)
    else:
        await verify_database_head(target_engine)
