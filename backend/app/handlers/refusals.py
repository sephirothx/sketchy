"""The refused acknowledgement, in the one shape the socket client reads.

A refusal used to be `{"ok": false, "error": "<sentence>"}` plus, on a handful
of paths, a boolean nobody else set - `roomFull`, `codeRetired`,
`serverPaused`. The client had two ways to find out *why* it was refused: read
the boolean if that path had one, or compare the sentence. `useCanvasProtocol`
really did compare "Drawing actions are out of sequence", so a copy edit could
change recovery behaviour, and the booleans were mutually ambiguous - a
response could carry none, or in principle two. #565 replaced both with one
discriminator:

    {"ok": false, "errorCode": "canvas_out_of_sequence", "error": "...", "field"?: ...}

`errorCode` rather than `code`, because `code` already means the invite code in
a successful room-entry acknowledgement. `retryAfterMs` is set where the server
knows when trying again could work (a command budget, a vote cooldown).

The codes themselves live in [`app/refusals.py`](../refusals.py), because REST
raises the same vocabulary through `app/api/errors.py` and a sibling package
cannot own it (#760). `error` is no longer read by anybody: the client writes
the player's sentence from the code, and the prose here is for a log and a bug
report (R-I18N-01).

Three acknowledgements are deliberately *not* refusals in this shape, and are
documented as exceptions in docs/wire-protocol.md 2: `guess` answers with a
bare receipt, `session_ping` with a compact tuple, and a throttled `draw`
answers nothing at all.
"""
from __future__ import annotations

from typing import Mapping

from app.refusals import ErrorCode

__all__ = ["ErrorCode", "refuse"]


def refuse(
    code: ErrorCode,
    error: str,
    *,
    field: str | None = None,
    params: Mapping[str, object] | None = None,
    retry_after_ms: int | None = None,
    **extra: object,
) -> dict[str, object]:
    """The refused acknowledgement, in the one shape the client reads.

    `params` carries the values the player's sentence needs - a count, a
    limit, a reason slug - and never a rendered fragment, for the reason
    R-I18N-02 gives. It is the same field `Refusal` puts in an HTTP body, so
    one client helper reads both.
    """
    response: dict[str, object] = {"ok": False, "errorCode": code, "error": error}
    if field:
        response["field"] = field
    if params:
        response["params"] = dict(params)
    if retry_after_ms is not None:
        response["retryAfterMs"] = retry_after_ms
    response.update(extra)
    return response
