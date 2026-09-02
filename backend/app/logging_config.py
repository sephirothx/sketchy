"""Make the application's own log lines reach somebody, in a shape a machine can read.

`LOG_LEVEL` had only ever been handed to uvicorn, which configures its own
loggers and nothing else. The two trees this project logs to - `app.*` from
module `__name__`, and the older `sketchy.*` names - had no handler at all, so
every logger.info and logger.exception in the codebase was written into
nothing: mail that could not be sent, a failing outbox sweep, a report being
filed, a game whose history could not be saved.

That is worse than quiet. The zero-configuration deployment this project
documents has no SMTP, and its console transport answers that by logging the
message it would have sent. If the log goes nowhere, the account recovery flow
silently does nothing at all on the default deployment.

Since #472 the lines also carry who they belong to and can be read by a
machine. Every record gets the request id, socket id and command that were
current when it was written (`app.correlation`), so the lines of one request
can be found together. In production the format is one JSON object per line -
`LOG_FORMAT=json`, the default when `SKETCHY_ENV=production` - because a log
that has to be parsed by regular expression is a log nobody parses. And every
line, in either format, passes through a redaction filter before it is
written: a bearer token, a password in a query string, a session cookie, a
password inside a database URL, or an e-mail address is replaced before it
can reach a log store that is kept longer than the data it came from.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import re
import sys
import traceback

from app import correlation
from app.deployment import is_production


TREES = ("app", "sketchy", "uvicorn")
FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
JSON_FORMAT = "json"
TEXT_FORMAT = "text"
FORMATS = (JSON_FORMAT, TEXT_FORMAT)

# The order matters: a bearer token inside a URL must be hidden as a token,
# not left because the URL rule ran first and saw no password.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 ***"),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|"
            r"[a-z_]*session|cookie)(\s*[:=]\s*)([^\s;,&\"']+)"
        ),
        r"\1\2***",
    ),
    # A database or relay URL with credentials in it.
    (re.compile(r"://([^:/@\s]+):([^@\s]+)@"), r"://\1:***@"),
    # The local part of an address is the personal half; the domain says
    # which relay or provider was involved, which is what a failure needs.
    (re.compile(r"[\w.+-]+@((?:[\w-]+\.)+[\w-]{2,})"), r"***@\1"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def log_format(environ: dict[str, str] | None = None) -> str:
    """`LOG_FORMAT` if set to a known value, else JSON in production and text elsewhere."""
    values = os.environ if environ is None else environ
    raw = values.get("LOG_FORMAT", "").strip().lower()
    if raw in FORMATS:
        return raw
    return JSON_FORMAT if is_production(values) else TEXT_FORMAT


class CorrelationFilter(logging.Filter):
    """Stamp every record with the request or command it was written inside."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in correlation.current().items():
            if not getattr(record, key, None):
                setattr(record, key, value)
        return True


class RedactingFormatter(logging.Formatter):
    """The text format, with the correlation fields as a suffix and secrets removed."""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        suffix = " ".join(
            f"{key}={getattr(record, key)}"
            for key in ("request_id", "sid", "event")
            if getattr(record, key, None)
        )
        if suffix:
            line = f"{line} [{suffix}]"
        return redact(line)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with a fixed set of keys a log store can index."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key in ("request_id", "sid", "event"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict) and fields:
            payload["fields"] = {
                str(key): (redact(value) if isinstance(value, str) else value)
                for key, value in fields.items()
            }
        if record.exc_info:
            payload["exc"] = redact("".join(traceback.format_exception(*record.exc_info)))
        elif record.exc_text:
            payload["exc"] = redact(record.exc_text)
        return json.dumps(payload, ensure_ascii=False, default=str)


def make_formatter(fmt: str | None = None) -> logging.Formatter:
    return JsonFormatter() if (fmt or log_format()) == JSON_FORMAT else RedactingFormatter(FORMAT)


def configure_logging(level: str | None = None, *, fmt: str | None = None) -> None:
    """Attach one stream handler to each of the application's logger trees.

    Idempotent, because the server entry point, the app's lifespan and a test
    may all call it; a second call with a different format replaces the
    formatter rather than adding a handler. Handlers are attached to the trees
    rather than the root so that anything else attached to root - pytest's
    caplog included - is left exactly as it is. The uvicorn tree is one of
    them since #472: the server is started with uvicorn's own logging config
    switched off, so its lines take the same shape as ours.
    """
    resolved = (level or os.getenv("LOG_LEVEL", "info")).upper()
    numeric = getattr(logging, resolved, logging.INFO)
    formatter = make_formatter(fmt)
    for name in TREES:
        logger = logging.getLogger(name)
        logger.setLevel(numeric)
        existing = [h for h in logger.handlers if getattr(h, "_sketchy_handler", False)]
        if existing:
            for handler in existing:
                handler.setFormatter(formatter)
            continue
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        handler.addFilter(CorrelationFilter())
        handler._sketchy_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        # Propagation is left on. Nothing configures the root logger here, so
        # there is no duplicate to avoid - and switching it off would cut these
        # records off from anything that attaches to root later, pytest's
        # caplog included.
