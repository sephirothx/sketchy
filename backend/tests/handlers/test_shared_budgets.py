"""Chat and reports are budgeted per person, not per socket (#1243).

A budget keyed by socket multiplies with the sockets somebody opens: one guest
on nine sockets had all 54 of 54 lobby lines accepted in 0.01 s - the whole
backlog every arriving player is handed - and eight accounts on one address
filed 56 reports over the socket, which charged no report bucket at all.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import socketio
from sqlalchemy import func, select

from app.db.models import PlayerReport, User
from app.handlers import register_all_handlers as register_handlers
from app.handlers.budgets import (
    LOBBY_CHAT,
    SHARED_CLASSES,
    SHARED_SWEEP_INTERVAL,
    Budget,
    CommandBudgets,
)
from app.handlers.context import HandlerContext
from app.refusals import ErrorCode
from app.rooms import RoomManager
from app.services import player_reports
from app.services.player_reports import ReportBudget
from app.services.presence import PresenceRegistry

from tests.dbfixtures import create_test_db
from tests.handlers.test_lobby_chat import arrive, chat_emits, identity, lobby_stack, say
from tests.handlers.test_lobby_presence import account_cookies

# --- the windows themselves ----------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_window_that_refuses_spends_nothing_from_the_others():
    budgets = CommandBudgets(clock=Clock())
    person, household = Budget(limit=5, window_seconds=10), Budget(limit=2, window_seconds=10)
    assert budgets.check_shared([("address:a", household), ("account:x", person)])
    assert budgets.check_shared([("address:a", household), ("account:y", person)])
    # The address is spent; the third account's line is refused ...
    assert not budgets.check_shared([("account:z", person), ("address:a", household)])
    # ... and cost that account nothing: its own window is still empty.
    assert all(
        budgets.check_shared([("account:z", person)]) for _ in range(person.limit)
    )


def test_windows_nobody_owns_are_swept_once_they_lapse():
    clock = Clock()
    budgets = CommandBudgets(clock=clock)
    budget = Budget(limit=1, window_seconds=10)
    for index in range(SHARED_SWEEP_INTERVAL - 1):
        budgets.check_shared([(f"account:{index}", budget)])
    assert budgets.tracked_shared_keys() == SHARED_SWEEP_INTERVAL - 1
    clock.now += 11
    budgets.check_shared([("account:late", budget)])
    assert budgets.tracked_shared_keys() == 1


# --- lobby chat ----------------------------------------------------------------------


async def test_one_account_on_many_sockets_has_one_sockets_allowance(monkeypatch):
    ctx, sio, _ = lobby_stack(monkeypatch)
    sockets = [f"sid-a{index}" for index in range(6)]
    for sid in sockets:
        await arrive(ctx, sio, sid, "tok-a")

    answers = [await say(sio, sid, f"line {index}") for index in range(3) for sid in sockets]

    accepted = [answer for answer in answers if answer["ok"]]
    assert len(accepted) == LOBBY_CHAT.default.limit
    assert len(chat_emits(sio)) == LOBBY_CHAT.default.limit
    refused = [answer for answer in answers if not answer["ok"]]
    assert {answer["errorCode"] for answer in refused} == {ErrorCode.TOO_FAST}
    assert ctx.lobby_chat.last_seq == LOBBY_CHAT.default.limit


async def test_one_address_shares_a_multiple_of_it_across_accounts(monkeypatch):
    ctx, sio, _ = lobby_stack(monkeypatch)
    ctx.command_budgets.set_limit(LOBBY_CHAT.name, 2)
    share = SHARED_CLASSES[LOBBY_CHAT.name]
    accounts = {f"tok-{index}": f"user-{index}" for index in range(share + 2)}
    account_cookies(monkeypatch, accounts)
    for user_id in accounts.values():
        ctx.presence_identities.remember(identity(user_id, user_id.title()))
    monkeypatch.setattr(ctx, "client_address", lambda sid: "203.0.113.7")
    for token in accounts:
        await arrive(ctx, sio, f"sid-{token}", token)

    answers = [await say(sio, f"sid-{token}", "hello") for token in accounts for _ in range(2)]

    assert sum(answer["ok"] for answer in answers) == 2 * share
    # The accounts the address refused spent none of their own allowance:
    # from a socket on another address, the last one still has all of it.
    last = f"tok-{share + 1}"
    monkeypatch.setattr(ctx, "client_address", lambda sid: "198.51.100.9")
    await arrive(ctx, sio, "sid-elsewhere", last)
    assert (await say(sio, "sid-elsewhere", "from elsewhere"))["ok"] is True
    await arrive(ctx, sio, "sid-elsewhere-0", "tok-0")
    assert (await say(sio, "sid-elsewhere-0", "from elsewhere"))["ok"] is False


# --- room conversation ---------------------------------------------------------------


async def test_the_room_conversation_allowance_is_per_account_too():
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = HandlerContext(sio, RoomManager())
    ctx.presence = PresenceRegistry()
    handler = AsyncMock(return_value={"ok": True})
    ctx.on("send_chat", handler)
    ctx.on("guess", handler)
    for sid in ("tab-1", "tab-2", "tab-3"):
        ctx.presence.note_socket_opened(sid, "user-ada")
    limit = ctx.command_budgets.for_command("send_chat").limit

    answers = [
        await sio.handlers["/"][command](sid, {"text": "hi"})
        for _ in range(limit)
        for sid in ("tab-1", "tab-2", "tab-3")
        for command in ("send_chat",)
    ]

    assert sum(answer["ok"] for answer in answers) == limit
    assert handler.await_count == limit


# --- reports -------------------------------------------------------------------------


async def _reporting_room(factory, reporters: int):
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    room.max_players = reporters + 1
    target_id = uuid4()
    target = room_manager.add_player(room, "Target", user_id=str(target_id), is_anonymous=False)
    target.sid = "target-sid"
    sessions = {"target-sid": {"room_id": room.id, "player_id": target.id}}
    users = [(target_id, "Target")]
    for index in range(reporters):
        account = uuid4()
        seat = room_manager.add_player(room, f"R{index}", user_id=str(account), is_anonymous=False)
        seat.sid = f"reporter-{index}"
        sessions[seat.sid] = {"room_id": room.id, "player_id": seat.id}
        users.append((account, f"R{index}"))
    async with factory() as session, session.begin():
        session.add_all(
            User(id=account, username=name, password_hash="hash", display_name=name, state="registered")
            for account, name in users
        )
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, session_factory=factory)
    sio.get_session = AsyncMock(side_effect=lambda sid, namespace=None: sessions[sid])
    sio.emit = AsyncMock()
    return sio, ctx, target


async def test_socket_reports_answer_to_the_address_bucket_rest_charges(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "report-budget-secret")
    factory, engine = await create_test_db()
    try:
        sio, ctx, target = await _reporting_room(factory, reporters=player_reports.REPORTS_PER_ADDRESS + 2)
        monkeypatch.setattr(ctx, "client_address", lambda sid: "203.0.113.7")
        body = {"targetPlayerId": target.id, "reason": "harassment", "details": "x"}

        answers = [
            await sio.handlers["/"]["report_player"](f"reporter-{index}", body)
            for index in range(player_reports.REPORTS_PER_ADDRESS + 2)
        ]

        assert [answer["ok"] for answer in answers] == (
            [True] * player_reports.REPORTS_PER_ADDRESS + [False, False]
        )
        assert answers[-1]["errorCode"] == ErrorCode.TOO_MANY_REPORTS
        async with factory() as session:
            filed = await session.scalar(select(func.count(PlayerReport.id)))
        assert filed == player_reports.REPORTS_PER_ADDRESS
        # The REST door reads the same rows: that address has nothing left.
        assert not await ReportBudget(factory).charge(address="203.0.113.7", account_id=str(uuid4()))
    finally:
        await engine.dispose()


async def test_an_account_is_budgeted_whichever_address_it_reports_from(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "report-budget-secret")
    monkeypatch.setattr(player_reports, "REPORTS_PER_ACCOUNT", 2)
    factory, engine = await create_test_db()
    try:
        budget = ReportBudget(factory)
        account = str(uuid4())
        spent = [
            await budget.charge(address=f"198.51.100.{index}", account_id=account)
            for index in range(3)
        ]
        assert spent == [True, True, False]
        # Refused by the account, so the address it came from paid nothing.
        other = ReportBudget(factory)
        assert all([
            await other.charge(address="198.51.100.2", account_id=str(uuid4()))
            for _ in range(player_reports.REPORTS_PER_ADDRESS)
        ])
    finally:
        await engine.dispose()


# --- retention -----------------------------------------------------------------------


def _chat_room(players: int, *, blocked: bool = False):
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    seats = []
    for index in range(players):
        seat = room_manager.add_player(room, f"P{index}", user_id=f"user-{index}", is_anonymous=False)
        seat.sid = f"sid-{index}"
        seats.append(seat)
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    ctx.message_retention = MagicMock(record=AsyncMock())
    ctx.block_service = MagicMock(
        blockers_of=AsyncMock(return_value=frozenset({"user-1"}) if blocked else frozenset())
    )
    sio.get_session = AsyncMock(
        side_effect=lambda sid, namespace=None: {"room_id": room.id, "player_id": seats[0].id}
    )
    sio.emit = AsyncMock()
    return sio, ctx, seats


async def test_a_line_nobody_else_received_is_not_kept():
    sio, ctx, seats = _chat_room(1)
    assert (await sio.handlers["/"]["send_chat"](seats[0].sid, {"text": "alone"}))["ok"] is True
    ctx.message_retention.record.assert_not_awaited()


async def test_a_line_every_other_seat_blocked_is_not_kept():
    sio, ctx, seats = _chat_room(2, blocked=True)
    assert (await sio.handlers["/"]["send_chat"](seats[0].sid, {"text": "unheard"}))["ok"] is True
    ctx.message_retention.record.assert_not_awaited()


async def test_a_line_somebody_else_received_is_kept():
    sio, ctx, seats = _chat_room(2)
    assert (await sio.handlers["/"]["send_chat"](seats[0].sid, {"text": "heard"}))["ok"] is True
    ctx.message_retention.record.assert_awaited_once()


async def test_a_seat_still_carrying_its_guest_id_spends_the_account_it_became(monkeypatch):
    """#1301 review: a room seat keeps the guest id it sat down with after that
    guest signs in to an account, and the socket door charged the bucket under
    it - one more account bucket per such seat, none shared with the REST and
    Gallery doors, which charge the account."""
    from app.db.models import IdentityAlias

    monkeypatch.setenv("IP_HASH_SECRET", "report-budget-secret")
    monkeypatch.setattr(player_reports, "REPORTS_PER_ACCOUNT", 2)
    factory, engine = await create_test_db()
    try:
        guest_id, account_id = uuid4(), uuid4()
        async with factory() as session, session.begin():
            session.add_all([
                User(id=guest_id, display_name="Guest"),
                User(id=account_id, username="Became", password_hash="hash", display_name="Became", state="registered"),
            ])
            await session.flush()
            session.add(IdentityAlias(source_user_id=guest_id, target_user_id=account_id))
        budget = ReportBudget(factory)
        spent = [
            await budget.charge(address=f"198.51.100.{index}", account_id=str(guest_id))
            for index in range(2)
        ]
        assert spent == [True, True]
        assert not await budget.charge(address="198.51.100.9", account_id=str(account_id))
    finally:
        await engine.dispose()
