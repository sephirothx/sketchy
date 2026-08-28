import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.timers import TimerManager


@pytest.mark.asyncio
async def test_naturally_completed_tasks_leave_every_registry():
    timers = TimerManager()
    phase = asyncio.create_task(asyncio.sleep(0))
    hint_one = asyncio.create_task(asyncio.sleep(0))
    hint_two = asyncio.create_task(asyncio.sleep(0))
    disconnect = asyncio.create_task(asyncio.sleep(0))
    restart = asyncio.create_task(asyncio.sleep(0))

    timers.replace_phase_timer("room", phase)
    timers.add_hint_timer("room", hint_one)
    timers.add_hint_timer("room", hint_two)
    timers.replace_disconnect_timer("player", disconnect)
    timers.replace_restart_timer("room", restart)

    await asyncio.gather(phase, hint_one, hint_two, disconnect, restart)
    await asyncio.sleep(0)

    assert timers.phase_timers == {}
    assert timers.hint_timers == {}
    assert timers.disconnect_timers == {}
    assert timers.restart_timers == {}


@pytest.mark.asyncio
async def test_cancel_methods_cancel_tasks_and_clear_registries():
    timers = TimerManager()
    phase = asyncio.create_task(asyncio.sleep(60))
    hint = asyncio.create_task(asyncio.sleep(60))
    disconnect = asyncio.create_task(asyncio.sleep(60))
    restart = asyncio.create_task(asyncio.sleep(60))
    timers.replace_phase_timer("room", phase)
    timers.add_hint_timer("room", hint)
    timers.replace_disconnect_timer("player", disconnect)
    timers.replace_restart_timer("room", restart)

    timers.cancel_phase_timer("room")
    timers.cancel_hint_timers("room")
    timers.cancel_disconnect_timer("player")
    timers.cancel_restart_timer("room")
    await asyncio.gather(phase, hint, disconnect, restart, return_exceptions=True)

    assert phase.cancelled()
    assert hint.cancelled()
    assert disconnect.cancelled()
    assert restart.cancelled()
    assert timers.phase_timers == {}
    assert timers.hint_timers == {}
    assert timers.disconnect_timers == {}
    assert timers.restart_timers == {}


@pytest.mark.asyncio
async def test_completed_replaced_task_cannot_remove_its_replacement():
    timers = TimerManager()
    old_phase = asyncio.create_task(asyncio.sleep(60))
    new_phase = asyncio.create_task(asyncio.sleep(60))
    old_disconnect = asyncio.create_task(asyncio.sleep(60))
    new_disconnect = asyncio.create_task(asyncio.sleep(60))

    timers.replace_phase_timer("room", old_phase)
    timers.replace_phase_timer("room", new_phase)
    timers.replace_disconnect_timer("player", old_disconnect)
    timers.replace_disconnect_timer("player", new_disconnect)
    await asyncio.sleep(0)

    assert old_phase.cancelled()
    assert old_disconnect.cancelled()
    assert timers.phase_timers["room"] is new_phase
    assert timers.disconnect_timers["player"] is new_disconnect

    await timers.close()


@pytest.mark.asyncio
async def test_repeated_disconnect_registration_keeps_only_latest_task():
    timers = TimerManager()
    tasks = [asyncio.create_task(asyncio.sleep(60)) for _ in range(3)]

    for task in tasks:
        timers.replace_disconnect_timer("player", task)
        await asyncio.sleep(0)

    assert all(task.cancelled() for task in tasks[:-1])
    assert timers.disconnect_timers == {"player": tasks[-1]}

    await timers.close()


@pytest.mark.asyncio
async def test_close_cancels_and_awaits_outstanding_tasks():
    timers = TimerManager()
    cleaned_up = asyncio.Event()

    async def wait_until_cancelled():
        try:
            await asyncio.sleep(60)
        finally:
            await asyncio.sleep(0)
            cleaned_up.set()

    task = asyncio.create_task(wait_until_cancelled())
    timers.replace_phase_timer("room", task)
    await asyncio.sleep(0)

    await timers.close()

    assert task.cancelled()
    assert cleaned_up.is_set()
    assert timers.phase_timers == {}
    assert timers.hint_timers == {}
    assert timers.disconnect_timers == {}
    assert timers.restart_timers == {}


@pytest.mark.asyncio
async def test_application_lifespan_closes_timer_manager(monkeypatch):
    from app import main

    monkeypatch.setenv("SHUTDOWN_DRAIN_SECONDS", "0")
    timers = TimerManager()
    dispose = AsyncMock()
    monkeypatch.setattr(main.handler_context, "timers", timers)
    monkeypatch.setattr(main, "async_engine", SimpleNamespace(dispose=dispose))
    monkeypatch.setattr(main, "init_db", AsyncMock())
    purge_messages = AsyncMock()
    monkeypatch.setattr(main, "purge_expired_room_messages", purge_messages)
    purge_abandonments = AsyncMock()
    monkeypatch.setattr(
        main, "purge_expired_shutdown_abandonments", purge_abandonments
    )
    monkeypatch.setattr(main, "seed_prompt_lists", AsyncMock())
    monkeypatch.setattr(main, "adopt_stored_settings", AsyncMock())
    retire_room_codes = AsyncMock()
    monkeypatch.setattr(
        main.handler_context.room_codes,
        "retire_orphaned_ephemeral",
        retire_room_codes,
    )
    task = asyncio.create_task(asyncio.sleep(60))
    timers.replace_disconnect_timer("player", task)
    messages = iter(
        [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    await main.app({"type": "lifespan", "state": {}}, receive, send)

    assert task.cancelled()
    assert timers.disconnect_timers == {}
    assert timers.restart_timers == {}
    purge_messages.assert_awaited_once_with(main.async_session_factory)
    purge_abandonments.assert_awaited_once_with(main.async_session_factory)
    retire_room_codes.assert_awaited_once_with()
    dispose.assert_awaited_once_with()
    assert main.shutdown_coordinator.state == "stopped"
    assert sent == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]
