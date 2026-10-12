"""Log lines a machine can read, that name what they belong to, and keep secrets out."""
from __future__ import annotations

import json
import logging
import random
import re
import time

import pytest

from app import correlation
from app.logging_config import (
    ACCESS_LOGGER,
    FORMAT,
    JsonFormatter,
    TREES,
    UVICORN_TREES,
    _detach,
    configure_logging,
    log_format,
    make_formatter,
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
        # `normalize_email` stores any non-blank local part before the last
        # `@` and any domain with a dot, so the net has to be as wide as the
        # column. Each of these survived the tidier pattern that came before.
        ("refused foo!bar@example.test", "refused ***@example.test"),
        ('refused "foo"@example.test', "refused ***@example.test"),
        ("refused o'brien@example.test", "refused ***@example.test"),
        ("refused foo@a.b", "refused ***@a.b"),
        ("refused a=b#c{d}@example.test", "refused ***@example.test"),
        # Two addresses with nothing between them but local-part characters:
        # the second starts where the first one's domain ended.
        ("a@b.c!d@e.f and g@h.i", "***@b.c***@e.f and ***@h.i"),
        # And the lines it must still leave legible.
        ("postgresql+asyncpg://sketchy:pa55@db.internal:5432/x", "postgresql+asyncpg://sketchy:***@db.internal:5432/x"),
        ("array[i]@list is not an address", "array[i]@list is not an address"),
        ("api_key=ABC123&other=1", "api_key=***&other=1"),
        ("nothing to hide here", "nothing to hide here"),
    ],
)
def test_secrets_and_addresses_never_reach_the_line(text, expected):
    assert redact(text) == expected


# The rules as they were written before two of them were made linear, each a
# single regular expression: the URL password ran from every `://` to the next
# `@` or space, and an address's local part could start anywhere. What they
# masked is the specification; the rewrite has to agree on every line.
_QUADRATIC_REDACTIONS = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 ***"),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|"
            r"[a-z_]*session|cookie)(\s*[:=]\s*)([^\s;,&\"']+)"
        ),
        r"\1\2***",
    ),
    (re.compile(r"://([^:/@\s]+):([^@\s]+)@"), r"://\1:***@"),
    (re.compile(r"""(?:"[^"\s]*"|[^\s@,;:/<>()\[\]\\"]+)@((?:[\w-]+\.)+[\w-]+)"""), r"***@\1"),
)


def _quadratic_redact(text: str) -> str:
    for pattern, replacement in _QUADRATIC_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def test_lines_are_masked_exactly_as_the_single_patterns_masked_them():
    rng = random.Random(472)
    # Short lines built from the pieces that decide where a URL's credentials
    # or an address start and end - single characters alone almost never spell
    # either: characters allowed in a local part but not a domain, in both, the
    # delimiters, the quote, a URL's `://`, and whole domains and addresses, so
    # they abut, nest in quotes and in URLs, and run on.
    pieces = [
        "a", "1", "-", ".", "!", "'", "+", '"', "@", " ", ":", "/", ",", "[", "\\",
        "b.c", "@d.e", "://", "x@y.z", "password=",
    ]
    for _ in range(40_000):
        line = "".join(rng.choice(pieces) for _ in range(rng.randrange(1, 16)))
        assert redact(line) == _quadratic_redact(line), line


@pytest.mark.parametrize(
    "line",
    [
        "1.2." * 3000,  # no `@` at all
        "a" * 12_000 + "@",  # one `@`, and no domain after it
        "://a:" * 2400,  # a URL's start over and over, and no `@` to end a password
    ],
    ids=["no-at", "one-trailing-at", "userinfo-without-at"],
)
def test_a_long_line_redacts_in_linear_time(line):
    """`redact` runs on the event loop for every JSON line, and a line can carry
    client text: a pattern that retries a run from each of its characters took
    half a second on 12 KB, which stalls every room on the server."""
    elapsed = min(_timed(redact, line) for _ in range(3))
    assert elapsed < 0.05, f"{elapsed * 1000:.0f} ms"


def _timed(fn, arg) -> float:
    start = time.perf_counter()
    fn(arg)
    return time.perf_counter() - start


# --- wiring ------------------------------------------------------------------------


def test_configure_logging_is_idempotent_and_can_change_format(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("SKETCHY_ENV", raising=False)
    # From a clean slate, whatever earlier tests in this process attached: the
    # first call must install and the second must find what it installed, and
    # that has to hold inside this test rather than depend on which worker ran
    # what before it (the coverage floor was missed under sharding for that).
    for name in (*TREES, *UVICORN_TREES):
        _detach(name)
    assert not any(getattr(h, "_sketchy_handler", False) for h in logging.getLogger("app").handlers)
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


def test_an_exception_already_rendered_as_text_is_carried_as_the_exc_field():
    """A record whose traceback was formatted upstream carries `exc_text` and no
    `exc_info`; the line must still carry it, redacted like everything else."""
    record = logging.LogRecord("app", logging.ERROR, __file__, 1, "boom", None, None)
    # Password-shaped rather than key-shaped on purpose: the credential scan in
    # CI reads test sources too, and a string that looks like a real key is a
    # finding whatever it is for.
    record.exc_text = "Traceback: login failed password=hunter2 for x"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["exc"] == "Traceback: login failed password=*** for x"
