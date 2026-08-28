"""Supported deployment topology is explicit and enforced where observable."""

import pytest

from app.deployment import (
    MINIMUM_PYTHON_VERSION,
    current_environment,
    is_production,
    shutdown_drain_seconds,
    validate_database_configuration,
    validate_python_runtime,
    validate_worker_topology,
)


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"WEB_CONCURRENCY": "1"},
        {"UVICORN_WORKERS": "1"},
        {"WEB_CONCURRENCY": " 1 ", "UVICORN_WORKERS": "1"},
    ],
)
def test_single_worker_configuration_is_supported(environ):
    validate_worker_topology(environ)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("WEB_CONCURRENCY", "0"),
        ("WEB_CONCURRENCY", "2"),
        ("UVICORN_WORKERS", "8"),
        ("UVICORN_WORKERS", "auto"),
    ],
)
def test_multi_worker_or_ambiguous_configuration_fails_closed(variable, value):
    with pytest.raises(RuntimeError, match=variable):
        validate_worker_topology({variable: value})


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, 30.0),
        ({"SHUTDOWN_DRAIN_SECONDS": "0"}, 0.0),
        ({"SHUTDOWN_DRAIN_SECONDS": " 12.5 "}, 12.5),
        ({"SHUTDOWN_DRAIN_SECONDS": "300"}, 300.0),
    ],
)
def test_shutdown_drain_window_is_bounded_and_configurable(environ, expected):
    assert shutdown_drain_seconds(environ) == expected


@pytest.mark.parametrize("value", ["-1", "301", "forever", "nan", "inf"])
def test_invalid_shutdown_drain_window_fails_startup(value):
    with pytest.raises(RuntimeError, match="SHUTDOWN_DRAIN_SECONDS"):
        shutdown_drain_seconds({"SHUTDOWN_DRAIN_SECONDS": value})


def test_the_running_interpreter_meets_the_supported_minimum():
    validate_python_runtime()


@pytest.mark.parametrize("version", [(3, 11), (3, 12), (3, 13)])
def test_an_older_python_fails_before_startup_touches_state(version):
    with pytest.raises(RuntimeError, match="requires Python"):
        validate_python_runtime(version)


def test_a_newer_python_is_accepted():
    validate_python_runtime((MINIMUM_PYTHON_VERSION[0], MINIMUM_PYTHON_VERSION[1] + 1))


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, "development"),
        ({"SKETCHY_ENV": ""}, "development"),
        ({"SKETCHY_ENV": "   "}, "development"),
        ({"SKETCHY_ENV": "development"}, "development"),
        ({"SKETCHY_ENV": "test"}, "test"),
        ({"SKETCHY_ENV": "production"}, "production"),
        ({"SKETCHY_ENV": " Production "}, "production"),
    ],
)
def test_the_deployment_environment_defaults_to_development(environ, expected):
    assert current_environment(environ) == expected
    assert is_production(environ) is (expected == "production")


@pytest.mark.parametrize("value", ["prod", "staging", "PRODUCTIION", "1"])
def test_an_environment_nobody_defined_fails_closed(value):
    """A misspelling must not read as development and disarm every guard."""
    with pytest.raises(RuntimeError, match="SKETCHY_ENV"):
        current_environment({"SKETCHY_ENV": value})


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"SKETCHY_ENV": "development"},
        {"SKETCHY_ENV": "development", "DATABASE_URL": "sqlite:///./sketchy.db"},
        {"SKETCHY_ENV": "test"},
        {"SKETCHY_ENV": "test", "DATABASE_URL": "sqlite+aiosqlite:///./sketchy.db"},
    ],
)
def test_zero_configuration_sqlite_still_runs_outside_production(environ):
    validate_database_configuration(environ)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://user:password@db:5432/sketchy",
        "postgresql://user:password@db:5432/sketchy",
        "postgres://user:password@db:5432/sketchy",
    ],
)
def test_production_accepts_every_postgresql_spelling(url):
    validate_database_configuration({"SKETCHY_ENV": "production", "DATABASE_URL": url})


@pytest.mark.parametrize(
    "environ",
    [
        {"SKETCHY_ENV": "production"},
        {"SKETCHY_ENV": "production", "DATABASE_URL": ""},
        {"SKETCHY_ENV": "production", "DATABASE_URL": "   "},
    ],
)
def test_production_without_a_database_url_refuses_to_start(environ):
    """The fallback is a relative file, so silence here is durable data loss."""
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        validate_database_configuration(environ)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///./sketchy.db",
        "sqlite+aiosqlite:///./sketchy.db",
        "sqlite:////var/lib/sketchy/sketchy.db",
        "  sqlite:///./sketchy.db  ",
    ],
)
def test_production_refuses_sqlite_however_it_is_spelled(url):
    with pytest.raises(RuntimeError, match="SQLite is not supported"):
        validate_database_configuration(
            {"SKETCHY_ENV": "production", "DATABASE_URL": url}
        )
