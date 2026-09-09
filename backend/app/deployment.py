"""Deployment invariants that must fail before application startup mutates state."""

from collections.abc import Mapping
import ipaddress
import os
import sys
from urllib.parse import urlsplit


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
DEFAULT_PUBLIC_BASE_URL = "http://localhost:8000"


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


def public_base_url(environ: Mapping[str, str] | None = None) -> str:
    """Where this deployment is reached from outside: the base of every link
    in a mail message, and the origin a plain-HTTP request is sent to in
    production. The default is the development server."""

    values = os.environ if environ is None else environ
    return values.get("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL).rstrip("/")


def _is_loopback(hostname: str) -> bool:
    if hostname in ("localhost",) or hostname.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_public_base_url(environ: Mapping[str, str] | None = None) -> None:
    """Refuse a production deployment whose public address is not HTTPS.

    Every reset and confirmation link is built on it, the session cookie is
    `__Host-` prefixed and therefore only ever sent over TLS, and a plain
    request is redirected to it (#467): a production `PUBLIC_BASE_URL` that
    is still the development default would mail links nobody can use and
    redirect every visitor to a server that is not there. Only the origin is
    accepted - Sketchy is served at the root of its host, so a path here
    would be a base no route is under.
    """

    values = os.environ if environ is None else environ
    if not is_production(values):
        return
    raw_value = values.get("PUBLIC_BASE_URL", "")
    if not raw_value.strip():
        raise RuntimeError(
            f"PUBLIC_BASE_URL is required when {ENVIRONMENT_VARIABLE}={PRODUCTION}: "
            "the https origin players reach this deployment at, for example "
            "https://sketchy.example."
        )
    parts = urlsplit(raw_value.strip())
    hostname = parts.hostname or ""
    if parts.scheme != "https" or not hostname:
        raise RuntimeError(
            f"PUBLIC_BASE_URL must be an https origin when {ENVIRONMENT_VARIABLE}="
            f"{PRODUCTION}; got {raw_value.strip()!r}. Production speaks HTTPS only: "
            "the session cookie is never sent over plain HTTP and a plain request "
            "is redirected here."
        )
    if _is_loopback(hostname):
        raise RuntimeError(
            f"PUBLIC_BASE_URL names a loopback address ({hostname}), which no "
            f"player can reach; set it to the public https origin when "
            f"{ENVIRONMENT_VARIABLE}={PRODUCTION}."
        )
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise RuntimeError(
            "PUBLIC_BASE_URL must be an origin only (scheme, host and port): "
            "Sketchy is served at the root of its host, so a path, query or "
            "fragment here would be a base no route is under."
        )


def validate_mail_configuration(environ: Mapping[str, str] | None = None) -> None:
    """Refuse a production deployment with no relay to send through.

    Without ``SMTP_HOST`` the console transport answers a message by logging
    it (R-AUTH-12), which is what lets somebody confirm an address or follow
    a reset link on a self-hosted checkout that has no mail at all. In
    production the same fallback is two failures at once: every confirmation
    link, reset link and suspension notice is written into a log store kept
    far longer than the one-hour token it now carries and read by more people
    than the mailbox would have been, and meanwhile every player who forgets
    a password waits for a message that is never sent.

    Refusing at startup rather than at the moment somebody needs a reset is
    the point: a mail misconfiguration that only shows up in the recovery
    flow shows up to the one person who cannot report it.

    Imported locally for the reason ``validate_database_configuration`` has:
    this module is imported by the runner before the application is, and
    ``app.auth.mail`` reaches the ORM. Asking that module rather than reading
    the variable here keeps one definition of what "configured" means.
    """

    values = os.environ if environ is None else environ
    if not is_production(values):
        return

    from app.auth.mail import mail_is_configured

    if not mail_is_configured(values):
        raise RuntimeError(
            f"SMTP_HOST is required when {ENVIRONMENT_VARIABLE}={PRODUCTION}. "
            "Without a relay the outbox falls back to logging each message, "
            "which would write confirmation and reset links into the "
            "application log and send nothing to the player waiting for one."
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
