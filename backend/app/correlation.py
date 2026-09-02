"""Who a log line belongs to: the request or the command that was running.

A line that says "Failed to persist game history for room ABCD" is only
half a fact without the request or socket command it happened inside.
Before #472 the request id existed only for the handful of endpoints that
write an audit row, was minted inside each of them, and reached nothing
else - not the response, not a log line, not the command handlers.

These context variables carry the identity down every `await` from the
place it is known - the timing middleware for HTTP, the command door for
Socket.IO - to every logger underneath, without any of them having to be
told. Task-local by construction: python-socketio runs each handler in its
own task, and a task inherits the context it was created in, so two
commands in flight cannot see each other's id.
"""
from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

request_id: ContextVar[str | None] = ContextVar("sketchy_request_id", default=None)
socket_sid: ContextVar[str | None] = ContextVar("sketchy_socket_sid", default=None)
socket_event: ContextVar[str | None] = ContextVar("sketchy_socket_event", default=None)

REQUEST_ID_HEADER = "x-request-id"


def new_request_id() -> str:
    """A fresh id, the same kind the audit ledger already keys on (UUIDv7)."""
    # Imported here so this module stays importable from anywhere, including
    # the logging setup that runs before the database package is wanted.
    from app.db.models import generate_uuid

    return str(generate_uuid())


def accepted_request_id(supplied: str | bytes | None) -> str | None:
    """A caller's id, if it is a UUID; anything else is ignored, not trusted.

    A proxy or a client may supply one so that its own logs and ours agree.
    It goes into log lines and the audit ledger, so it has to be a shape
    that cannot smuggle text in: a UUID and nothing else.
    """
    if not supplied:
        return None
    if isinstance(supplied, bytes):
        supplied = supplied.decode("ascii", "ignore")
    try:
        return str(UUID(supplied.strip()))
    except ValueError:
        return None


def current() -> dict[str, str]:
    """The correlation fields that are set right now, for a log record."""
    fields: dict[str, str] = {}
    rid = request_id.get()
    if rid:
        fields["request_id"] = rid
    sid = socket_sid.get()
    if sid:
        fields["sid"] = sid
    event = socket_event.get()
    if event:
        fields["event"] = event
    return fields
