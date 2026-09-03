"""Log lines a machine can read, that name what they belong to, and keep secrets out."""
from __future__ import annotations

import json
import logging

import pytest

from app import correlation
from app.logging_config import (
    ACCESS_LOGGER,
    FORMAT,
    JsonFormatter,
    configure_logging,
    make_formatter,
    log_format,
    redact,
)


def record(message: str, *args, level=logging.INFO, name="app.test", **kwargs) -> logging.LogRecord:
    rec = logging.LogRecord(name, level, __file__, 1, message, args, None)
    for key, value in kwargs.items():
        setattr(rec, key, value)
    return rec


# --- format selection ------------------------------------------------------------


def test_json_is_the_production_default_and_text_the_development_one():
    assert log_format({}) == "text"
    assert log_format({"SKETCHY_ENV": "production"}) == "json"
    assert log_format({"SKETCHY_ENV": "production", "LOG_FORMAT": "text"}) == "text"
    assert log_format({"LOG_FORMAT": "JSON"}) == "json"
    # A value nobody defined does not pick a format by accident.
    assert log_format({"LOG_FORMAT": "yaml"}) == "text"


# --- JSON lines --------------------------------------------------------------------


def test_every_json_line_parses_and_carries_the_fixed_keys():
    formatter = JsonFormatter()
    line = formatter.format(record("hello %s", "world"))
    payload = json.loads(line)
    assert set(payload) == {"ts", "level", "logger", "msg"}
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["ts"].endswith("+00:00")


def test_correlation_and_extra_fields_ride_along_when_present():
    formatter = JsonFormatter()
    payload = json.loads(
        formatter.format(
            record(
                "GET /api/rooms -> 200",
                request_id="rid-1",
                sid="sid-1",
                event="draw",
                fields={"status": 200, "ms": 3.2, "note": "user@example.com"},
            )
        )
    )
    assert payload["request_id"] == "rid-1"
    assert payload["sid"] == "sid-1"
    assert payload["event"] == "draw"
    assert payload["fields"]["status"] == 200
    # Redaction reaches inside the extra fields too.
    assert payload["fields"]["note"] == "***@example.com"


def test_an_exception_is_one_string_field_not_a_dozen_lines():
    formatter = JsonFormatter()
    try:
        raise RuntimeError("password=hunter2 leaked")
    except RuntimeError:
        import sys

        rec = record("boom", level=logging.ERROR)
        rec.exc_info = sys.exc_info()
    payload = json.loads(formatter.format(rec))
    assert "RuntimeError" in payload["exc"]
    assert "hunter2" not in payload["exc"]
    assert "\n" in payload["exc"]  # one JSON line on the wire, a traceback inside it


# --- text lines ------------------------------------------------------------------


def test_the_text_format_is_the_development_console_verbatim():
    """No suffix, no redaction: a developer reads it, and the console mail
    transport prints reset links here that a masked `token=` would break."""
    formatter = make_formatter("text")
    assert type(formatter) is logging.Formatter
    assert formatter._fmt == FORMAT
    line = formatter.format(
        record("reset link: http://x/reset-password?token=abc for user@example.com", request_id="rid-1")
    )
    assert line.endswith("INFO     app.test: reset link: http://x/reset-password?token=abc for user@example.com")


# --- redaction ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Authorization: Bearer abc.DEF-123", "Authorization: Bearer ***"),
        ("login failed password=hunter2 for x", "login failed password=*** for x"),
        ("Authorization: Basic dXNlcjpwYXNz", "Authorization: Basic ***"),
        ("token: s3cr3t; retry", "token: ***; retry"),
        ("cookie sketchy_session=deadbeef; Path=/", "cookie sketchy_session=***; Path=/"),
        ("postgresql+asyncpg://sketchy:pa55@db:5432/sketchy", "postgresql+asyncpg://sketchy:***@db:5432/sketchy"),
        ("could not send to alice.smith+x@example.co.uk", "could not send to ***@example.co.uk"),
        ("api_key=ABC123&other=1", "api_key=***&other=1"),
        ("nothing to hide here", "nothing to hide here"),
    ],
)
def test_secrets_and_addresses_never_reach_the_line(text, expected):
    assert redact(text) == expected


# --- wiring ------------------------------------------------------------------------


def test_configure_logging_is_idempotent_and_can_change_format(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("SKETCHY_ENV", raising=False)
    configure_logging(fmt="text")
    configure_logging(fmt="text")
    app_logger = logging.getLogger("app")
    ours = [h for h in app_logger.handlers if getattr(h, "_sketchy_handler", False)]
    assert len(ours) == 1
    assert type(ours[0].formatter) is logging.Formatter
    # In text mode uvicorn is left to its own config, and the access line
    # that would duplicate its access log is held back.
    assert not any(getattr(h, "_sketchy_handler", False) for h in logging.getLogger("uvicorn").handlers)
    assert logging.getLogger(ACCESS_LOGGER).getEffectiveLevel() == logging.WARNING
    configure_logging(fmt="json")
    ours = [h for h in app_logger.handlers if getattr(h, "_sketchy_handler", False)]
    assert len(ours) == 1
    assert isinstance(ours[0].formatter, JsonFormatter)
    # uvicorn's tree is ours in JSON mode, since the server hands its config over.
    assert any(getattr(h, "_sketchy_handler", False) for h in logging.getLogger("uvicorn").handlers)
    assert logging.getLogger(ACCESS_LOGGER).getEffectiveLevel() == logging.INFO
    # And back again, cleanly.
    configure_logging(fmt="text")
    assert not any(getattr(h, "_sketchy_handler", False) for h in logging.getLogger("uvicorn").handlers)


def test_records_written_inside_a_request_are_stamped_with_it():
    """The filter and the formatter together, on a handler of this test's own."""
    import io

    from app.logging_config import CorrelationFilter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CorrelationFilter())
    logger = logging.getLogger("app.stamped")
    logger.addHandler(handler)
    try:
        token = correlation.request_id.set("rid-42")
        try:
            logger.warning("inside")
        finally:
            correlation.request_id.reset(token)
        logger.warning("outside")
    finally:
        logger.removeHandler(handler)
    lines = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
    inside = next(line for line in lines if line["msg"] == "inside")
    outside = next(line for line in lines if line["msg"] == "outside")
    assert inside["request_id"] == "rid-42"
    assert "request_id" not in outside
