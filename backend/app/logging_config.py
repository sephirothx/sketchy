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

Since #472 there are two formats, for two readers.

`LOG_FORMAT=json` - the default when `SKETCHY_ENV=production` - is for a log
store. One object per line, because a log that has to be parsed by regular
expression is a log nobody parses; every record stamped with the request id,
socket id and command that were current when it was written
(`app.correlation`), so the lines of one request can be found together; and
every line passed through a redaction filter first, so a bearer token, a
password in a query string, a session cookie, a password inside a database
URL or an e-mail address cannot reach a store kept longer than the data it
came from. In this mode uvicorn's own logging is switched off by the server
entry point and its loggers attached here, so its lines take the same shape,
and the timing middleware's one access line per request replaces uvicorn's.

`LOG_FORMAT=text` - the default everywhere else - is the development
console, and it is deliberately what it was before #472: the plain line,
uvicorn's own coloured lines and access log left exactly as uvicorn writes
them, nothing redacted. A developer reads this with their eyes, and the
zero-configuration deployment prints the verification and reset links here
with their tokens in them - a console that masked those would break the
account flow it exists to make work. The request id is still on every
response as `X-Request-ID`; it just is not on every line.
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


TREES = ("app", "sketchy")
# Taken over only in JSON mode; in text mode uvicorn keeps its own config.
UVICORN_TREES = ("uvicorn",)
ACCESS_LOGGER = "sketchy.http"
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
    return JsonFormatter() if (fmt or log_format()) == JSON_FORMAT else logging.Formatter(FORMAT)


def _detach(name: str) -> None:
    logger = logging.getLogger(name)
    for handler in [h for h in logger.handlers if getattr(h, "_sketchy_handler", False)]:
        logger.removeHandler(handler)


def configure_logging(level: str | None = None, *, fmt: str | None = None) -> None:
    """Attach one stream handler to each of the application's logger trees.

    Idempotent, because the server entry point, the app's lifespan and a test
    may all call it; a second call with a different format replaces the
    formatter rather than adding a handler. Handlers are attached to the trees
    rather than the root so that anything else attached to root - pytest's
    caplog included - is left exactly as it is.

    In JSON mode the uvicorn tree is ours as well (the server starts uvicorn
    with its own config switched off) and the access logger writes at the
    configured level. In text mode uvicorn is left alone and the access
    logger is held at WARNING, because uvicorn's own access log is back and
    a second line per request would be noise.
    """
    resolved = (level or os.getenv("LOG_LEVEL", "info")).upper()
    numeric = getattr(logging, resolved, logging.INFO)
    chosen = fmt or log_format()
    formatter = make_formatter(chosen)
    if chosen == JSON_FORMAT:
        trees = (*TREES, *UVICORN_TREES)
        logging.getLogger(ACCESS_LOGGER).setLevel(logging.NOTSET)
    else:
        trees = TREES
        for name in UVICORN_TREES:
            _detach(name)
        logging.getLogger(ACCESS_LOGGER).setLevel(logging.WARNING)
    for name in trees:
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
