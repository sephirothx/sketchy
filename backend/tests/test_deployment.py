"""Supported deployment topology is explicit and enforced where observable."""

import pytest

from app.deployment import (
    MINIMUM_PYTHON_VERSION,
    current_environment,
    is_production,
    public_base_url,
    shutdown_drain_seconds,
    validate_database_configuration,
    validate_mail_configuration,
    validate_public_base_url,
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
    with pytest.raises(RuntimeError, match="names a SQLite database"):
        validate_database_configuration(
            {"SKETCHY_ENV": "production", "DATABASE_URL": url}
        )


def test_the_rejected_url_is_named_but_never_reproduced():
    """This message goes straight into a deployment log.

    A connection URL carries a password and whatever else is in its query
    string, so the refusal says which variable was wrong, not what was in it.
    """
    secret = "sqlite:///./sketchy.db?key=hunter2"
    with pytest.raises(RuntimeError) as refusal:
        validate_database_configuration(
            {"SKETCHY_ENV": "production", "DATABASE_URL": secret}
        )
    message = str(refusal.value)
    assert "DATABASE_URL" in message
    assert "hunter2" not in message
    assert secret not in message


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"PUBLIC_BASE_URL": "http://localhost:8000"},
        {"SKETCHY_ENV": "development", "PUBLIC_BASE_URL": "http://localhost:8000"},
        {"SKETCHY_ENV": "test", "PUBLIC_BASE_URL": "http://127.0.0.1:8000"},
    ],
)
def test_a_plain_or_local_public_url_is_fine_outside_production(environ):
    validate_public_base_url(environ)


@pytest.mark.parametrize(
    "url",
    ["https://sketchy.example", "https://sketchy.example/", "https://play.sketchy.example:8443"],
)
def test_production_accepts_an_https_origin(url):
    validate_public_base_url({"SKETCHY_ENV": "production", "PUBLIC_BASE_URL": url})


@pytest.mark.parametrize(
    "url,reason",
    [
        ("", "is required"),
        ("   ", "is required"),
        ("http://sketchy.example", "must be an https origin"),
        ("sketchy.example", "must be an https origin"),
        ("https://localhost", "loopback"),
        ("https://127.0.0.1:8000", "loopback"),
        ("https://[::1]", "loopback"),
        ("https://sketchy.localhost", "loopback"),
        ("https://sketchy.example/play", "origin only"),
        ("https://sketchy.example/?x=1", "origin only"),
    ],
)
def test_production_refuses_a_public_url_that_is_not_its_https_origin(url, reason):
    """#467: links are built on it, the `__Host-` cookie is only ever sent
    over TLS, and a plain request is redirected to it - so the development
    default, a plain scheme, or a loopback name would each strand players."""
    with pytest.raises(RuntimeError, match=reason):
        validate_public_base_url({"SKETCHY_ENV": "production", "PUBLIC_BASE_URL": url})


def test_the_public_url_default_is_the_development_server():
    assert public_base_url({}) == "http://localhost:8000"
    assert public_base_url({"PUBLIC_BASE_URL": "https://sketchy.example/"}) == "https://sketchy.example"


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"SKETCHY_ENV": "development"},
        {"SKETCHY_ENV": "test"},
        {"SKETCHY_ENV": "development", "SMTP_HOST": ""},
    ],
)
def test_a_deployment_without_mail_still_runs_outside_production(environ):
    """R-AUTH-05 and R-AUTH-12: a checkout with no relay is a supported
    deployment, and its console transport is how account recovery completes
    there."""
    validate_mail_configuration(environ)


@pytest.mark.parametrize(
    "host",
    ["relay.example", " relay.example ", "127.0.0.1"],
)
def test_production_with_a_relay_starts(host):
    validate_mail_configuration({"SKETCHY_ENV": "production", "SMTP_HOST": host})


@pytest.mark.parametrize(
    "environ",
    [
        {"SKETCHY_ENV": "production"},
        {"SKETCHY_ENV": "production", "SMTP_HOST": ""},
        {"SKETCHY_ENV": "production", "SMTP_HOST": "   "},
    ],
)
def test_production_without_a_relay_refuses_to_start(environ):
    """#466: the fallback logs the message. In production that writes a live
    reset link into a log store and sends nothing to the player waiting for
    one - two failures, neither of them visible until somebody needs to
    recover an account."""
    with pytest.raises(RuntimeError, match="SMTP_HOST is required"):
        validate_mail_configuration(environ)


def test_the_mail_refusal_says_what_to_set_without_quoting_the_environment():
    """It goes straight into a deployment log, like the database one."""
    with pytest.raises(RuntimeError) as refusal:
        validate_mail_configuration(
            {"SKETCHY_ENV": "production", "SMTP_PASSWORD": "hunter2"}
        )
    message = str(refusal.value)
    assert "SMTP_HOST" in message
    assert "hunter2" not in message
