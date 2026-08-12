"""Own asyncio task lifecycle for game phases, hints, and disconnects."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


Task = asyncio.Task[Any]


@dataclass
class TimerManager:
    """Track, replace, cancel, and drain application-owned timer tasks."""

    phase_timers: dict[str, Task] = field(default_factory=dict)
    hint_timers: dict[str, set[Task]] = field(default_factory=dict)
    disconnect_timers: dict[str, Task] = field(default_factory=dict)

    def replace_phase_timer(self, room_id: str, task: Task) -> None:
        self.cancel_phase_timer(room_id)
        self.phase_timers[room_id] = task
        task.add_done_callback(
            lambda completed: self.remove_phase_timer(room_id, completed)
        )

    def remove_phase_timer(self, room_id: str, task: Task) -> None:
        """Deregister ``task`` only if it still owns the room's phase slot."""
        self._remove_if_current(self.phase_timers, room_id, task)

    def add_hint_timer(self, room_id: str, task: Task) -> None:
        self.hint_timers.setdefault(room_id, set()).add(task)
        task.add_done_callback(
            lambda completed: self._remove_hint_if_current(room_id, completed)
        )

    def replace_disconnect_timer(self, player_id: str, task: Task) -> None:
        self.cancel_disconnect_timer(player_id)
        self.disconnect_timers[player_id] = task
        task.add_done_callback(
            lambda completed: self._remove_if_current(
                self.disconnect_timers, player_id, completed
            )
        )

    def cancel_phase_timer(self, room_id: str) -> None:
        self._cancel_current(self.phase_timers, room_id)

    def cancel_hint_timers(self, room_id: str) -> None:
        tasks = self.hint_timers.pop(room_id, set())
        for task in tasks:
            if not task.done():
                task.cancel()

    def cancel_disconnect_timer(self, player_id: str) -> None:
        self._cancel_current(self.disconnect_timers, player_id)

    async def close(self) -> None:
        """Cancel and await every task still owned by the application."""
        tasks = [
            *self.phase_timers.values(),
            *(task for group in self.hint_timers.values() for task in group),
            *self.disconnect_timers.values(),
        ]
        self.phase_timers.clear()
        self.hint_timers.clear()
        self.disconnect_timers.clear()

        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _remove_hint_if_current(self, room_id: str, task: Task) -> None:
        tasks = self.hint_timers.get(room_id)
        if not tasks or task not in tasks:
            return
        tasks.remove(task)
        if not tasks:
            self.hint_timers.pop(room_id, None)

    @staticmethod
    def _remove_if_current(
        registry: dict[str, Task], key: str, task: Task
    ) -> None:
        if registry.get(key) is task:
            registry.pop(key, None)

    @staticmethod
    def _cancel_current(registry: dict[str, Task], key: str) -> None:
        task = registry.pop(key, None)
        if task is not None and not task.done():
            task.cancel()
