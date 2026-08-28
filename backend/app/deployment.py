"""Deployment invariants that must fail before application startup mutates state."""

from collections.abc import Mapping
import os
import sys


MINIMUM_PYTHON_VERSION = (3, 14)
SUPPORTED_APP_WORKERS = 1
WORKER_COUNT_ENVIRONMENTS = ("WEB_CONCURRENCY", "UVICORN_WORKERS")
DEFAULT_SHUTDOWN_DRAIN_SECONDS = 30.0
MAX_SHUTDOWN_DRAIN_SECONDS = 300.0
ENVIRONMENT_VARIABLE = "SKETCHY_ENV"
DEVELOPMENT = "development"
TEST = "test"
PRODUCTION = "production"
# Development is the default because a checkout has to run with nothing set.
# Production is therefore always something an operator asked for by name,
# which is the only reading under which refusing to start is fair.
SUPPORTED_ENVIRONMENTS = (DEVELOPMENT, TEST, PRODUCTION)
DEFAULT_ENVIRONMENT = DEVELOPMENT


def current_environment(environ: Mapping[str, str] | None = None) -> str:
    """Read the deployment environment, refusing a value nobody defined.

    A misspelling has to fail rather than fall back: ``SKETCHY_ENV=prod``
    silently treated as development is exactly the misconfiguration the
    production guards exist to catch, and it would disarm every one of them
    at once.
    """

    values = os.environ if environ is None else environ
    raw_value = values.get(ENVIRONMENT_VARIABLE)
    if raw_value is None or not raw_value.strip():
        return DEFAULT_ENVIRONMENT
    environment = raw_value.strip().lower()
    if environment not in SUPPORTED_ENVIRONMENTS:
        supported = ", ".join(SUPPORTED_ENVIRONMENTS)
        raise RuntimeError(
            f"{ENVIRONMENT_VARIABLE} must be one of {supported}; "
            f"got {raw_value.strip()!r}."
        )
    return environment


def is_production(environ: Mapping[str, str] | None = None) -> bool:
    """Whether the production-only invariants apply to this process."""

    return current_environment(environ) == PRODUCTION


def validate_database_configuration(environ: Mapping[str, str] | None = None) -> None:
    """Refuse to serve production traffic from a local single-writer file.

    Without ``DATABASE_URL`` the application falls back to a relative SQLite
    file, and a production deploy that forgot the variable then looks entirely
    healthy while writing accounts, moderation evidence, and history to
    storage the next container replacement throws away. SQLite also serializes
    every writer, so the fallback quietly caps a production server at one
    write at a time.

    Checked here rather than in ``get_database_url()`` so that importing
    ``app.db`` stays free of policy: the engine is built at import time, and a
    guard there would refuse the test suite as readily as a bad deploy.
    """

    values = os.environ if environ is None else environ
    if not is_production(values):
        return

    raw_value = values.get("DATABASE_URL")
    if raw_value is None or not raw_value.strip():
        raise RuntimeError(
            f"DATABASE_URL is required when {ENVIRONMENT_VARIABLE}={PRODUCTION}. "
            "Set it to a PostgreSQL URL, for example "
            "postgresql+asyncpg://user:password@host:5432/sketchy."
        )

    # Normalized by the same function the engine uses, so a URL is classified
    # here exactly as the driver will classify it moments later. Imported
    # locally: app.db builds an engine at import time, and this module is
    # imported by the runner before the application is.
    from app.db import get_database_url

    url = get_database_url(raw_value)
    if url.startswith("sqlite"):
        # The rejected value is named, never reproduced. A connection URL
        # carries a password and whatever else is in its query string, and
        # this message goes straight into a deployment log.
        raise RuntimeError(
            f"DATABASE_URL names a SQLite database, which is not supported "
            f"when {ENVIRONMENT_VARIABLE}={PRODUCTION}. Set it to a "
            "PostgreSQL URL, for example "
            "postgresql+asyncpg://user:password@host:5432/sketchy."
        )


def validate_python_runtime(version: tuple[int, ...] | None = None) -> None:
    """Refuse to start on a Python older than the one v1 supports.

    Sketchy targets a single Python version so that runtime-dependent
    behaviour - identifier generation, datetime handling, asyncio shutdown
    semantics - cannot differ between a developer's machine and production.
    """

    running = tuple(sys.version_info[:2]) if version is None else tuple(version[:2])
    if running < MINIMUM_PYTHON_VERSION:
        wanted = ".".join(str(part) for part in MINIMUM_PYTHON_VERSION)
        found = ".".join(str(part) for part in running)
        raise RuntimeError(
            f"Sketchy requires Python {wanted} or newer; this process is {found}."
        )


def validate_worker_topology(environ: Mapping[str, str] | None = None) -> None:
    """Reject common multi-worker configuration for process-owned live state.

    Uvicorn's command-line ``--workers`` option cannot be introspected from an
    imported ASGI application, so deployment commands must still omit it. The
    common environment-driven paths are rejected here instead of starting a
    topology that can split rooms, codes, timers, and socket sessions.
    """

    values = os.environ if environ is None else environ
    for variable in WORKER_COUNT_ENVIRONMENTS:
        raw_value = values.get(variable)
        if raw_value is None or not raw_value.strip():
            continue
        try:
            worker_count = int(raw_value)
        except ValueError as exc:
            raise RuntimeError(
                f"{variable} must be {SUPPORTED_APP_WORKERS}; got {raw_value!r}."
            ) from exc
        if worker_count != SUPPORTED_APP_WORKERS:
            raise RuntimeError(
                "Sketchy v1 supports exactly one application worker because "
                "live rooms, games, timers, and socket sessions are process-owned; "
                f"{variable} requested {worker_count}."
            )


def shutdown_drain_seconds(environ: Mapping[str, str] | None = None) -> float:
    """Parse the bounded planned-deploy drain window."""

    values = os.environ if environ is None else environ
    raw_value = values.get("SHUTDOWN_DRAIN_SECONDS")
    if raw_value is None or not raw_value.strip():
        return DEFAULT_SHUTDOWN_DRAIN_SECONDS
    try:
        seconds = float(raw_value)
    except ValueError as exc:
        raise RuntimeError("SHUTDOWN_DRAIN_SECONDS must be a number") from exc
    if not 0 <= seconds <= MAX_SHUTDOWN_DRAIN_SECONDS:
        raise RuntimeError(
            "SHUTDOWN_DRAIN_SECONDS must be between 0 and "
            f"{int(MAX_SHUTDOWN_DRAIN_SECONDS)}"
        )
    return seconds
