"""Supported deployment topology is explicit and enforced where observable."""

import pytest

from app.deployment import (
    MINIMUM_PYTHON_VERSION,
    shutdown_drain_seconds,
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
