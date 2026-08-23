"""Deployment invariants that must fail before application startup mutates state."""

from collections.abc import Mapping
import os
import sys


MINIMUM_PYTHON_VERSION = (3, 14)
SUPPORTED_APP_WORKERS = 1
WORKER_COUNT_ENVIRONMENTS = ("WEB_CONCURRENCY", "UVICORN_WORKERS")
DEFAULT_SHUTDOWN_DRAIN_SECONDS = 30.0
MAX_SHUTDOWN_DRAIN_SECONDS = 300.0


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
