"""Supported deployment topology is explicit and enforced where observable."""

import pytest

from app.deployment import validate_worker_topology


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
