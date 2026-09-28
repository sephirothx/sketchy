"""A command sent with no payload at all is a command with a missing one (#1235).

`HandlerContext.on` refused surplus arguments and nothing else, so `42["join_room"]`
called the handler with none: a `TypeError` for most of them, logged as a
traceback, and an acknowledgement id that was never answered. Every command
now reaches its handler with `None`, which each one already judges.
"""
from __future__ import annotations

import pytest

from app.rooms import RoomManager
from tests.handlers.test_command_budgets import build_stack


def _commands():
    ctx, sio, sessions = build_stack(RoomManager())
    return sorted(set(sio.handlers["/"]) - {"connect", "disconnect"})


@pytest.mark.parametrize("command", _commands())
async def test_a_command_with_no_payload_is_answered_not_a_type_error(command):
    ctx, sio, sessions = build_stack(RoomManager())
    await sessions.save("sid-1", {"user_id": "user-1"})

    answer = await sio.handlers["/"][command]("sid-1")

    if isinstance(answer, dict) and answer.get("ok") is False:
        # Refused, with a code the client can read - whichever the handler
        # reaches first for a caller with no payload and no room.
        assert isinstance(answer.get("errorCode"), str), answer


async def test_a_payload_command_called_with_nothing_is_an_invalid_payload():
    ctx, sio, sessions = build_stack(RoomManager())
    await sessions.save("sid-1", {"user_id": "user-1"})

    answer = await sio.handlers["/"]["join_room"]("sid-1")

    assert answer == {"ok": False, "errorCode": "invalid_payload", "error": answer["error"]}
