"""Per-turn canvas protocol state and drawing-history operations."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.canvas_history import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    HISTORY_HASH_INITIAL,
    MAX_CANVAS_ACTIONS,
    MAX_CANVAS_POINTS,
    PATH_TAG,
    PackedCanvasHistory,
    canvas_history_hash,
    color_to_int,
    extend_history_hash,
)


# The browser retains at most 256 unacknowledged mutations. Keeping twice that
# window lets the server answer ordinary duplicate deliveries without allowing
# per-turn acknowledgement state to grow with the sequence number forever.
MAX_CANVAS_COMMITS = 512


@dataclass
class CanvasSession:
    """Drawing state for one turn, identified by a room-assigned generation."""

    history: PackedCanvasHistory = field(default_factory=PackedCanvasHistory)
    revision: int = 0
    generation: int = 0
    sequence: int = 0
    hashes: list[int] = field(default_factory=list, repr=False, compare=False)
    commits: list[tuple[int, int, str]] = field(default_factory=list, repr=False, compare=False)
    commit_base_sequence: int = field(default=1, repr=False, compare=False)
    active_draw_sequence: int | None = field(default=None, repr=False, compare=False)
    discarding_draw_sequence: bool = field(default=False, repr=False, compare=False)
    active_path_index: int | None = field(default=None, repr=False, compare=False)
    point_count: int = field(default=0, repr=False, compare=False)

    def record_stroke(self, event: str, payload: dict) -> bool:
        if self.history.last_is_clear():
            if event == "clear_canvas":
                return True
            self.history.clear()
            self.hashes.clear()
            self.active_path_index = None
            self.point_count = 0
        if event == "draw_move":
            if self.active_path_index is None:
                return False
            if self.point_count + len(payload["points"]) > MAX_CANVAS_POINTS:
                return False
            self.history.extend_path(
                self.active_path_index,
                [(point["x"], point["y"]) for point in payload["points"]],
            )
            self.point_count += len(payload["points"])
            return True
        if event == "draw_end":
            if self.active_path_index is None:
                return False
            self.active_path_index = None
            self._finalize_history_action()
            return True
        if len(self.history) >= MAX_CANVAS_ACTIONS:
            return False
        self.active_path_index = None
        if event == "draw_start":
            if self.point_count >= MAX_CANVAS_POINTS:
                return False
            self.active_path_index = self.history.append_path(
                [(payload["x"], payload["y"])],
                color=color_to_int(payload["color"]),
                width=payload["width"],
            )
            self.point_count += 1
            self.revision += 1
            return True
        if event == "draw_shape":
            self.history.append_shape(
                shape=payload["shape"],
                start=(payload["from"]["x"], payload["from"]["y"]),
                end=(payload["to"]["x"], payload["to"]["y"]),
                color=color_to_int(payload["color"]),
                width=payload["width"],
            )
        elif event == "draw_fill":
            self.history.append_fill(
                x=min(CANVAS_WIDTH - 1, int(payload["x"] * CANVAS_WIDTH)),
                y=min(CANVAS_HEIGHT - 1, int(payload["y"] * CANVAS_HEIGHT)),
                color=color_to_int(payload["color"]),
            )
        else:
            return False
        self.revision += 1
        self._finalize_history_action()
        return True

    def clear_canvas_stroke(self) -> bool:
        """Record a clear action so Undo can restore the preceding history."""
        if (
            not self.history
            or self.history.last_is_clear()
            or len(self.history) >= MAX_CANVAS_ACTIONS
        ):
            return False
        self.active_path_index = None
        self.history.append_clear()
        self.revision += 1
        self._finalize_history_action()
        return True

    def sync_payload(self) -> bytes:
        return self.history.binary_payload()

    @property
    def hash(self) -> int:
        if len(self.hashes) == len(self.history):
            return self.hashes[-1] if self.hashes else HISTORY_HASH_INITIAL
        if len(self.hashes) == len(self.history) - 1:
            # A path is still being drawn, so its own record is the only one
            # missing from the prefix array. Hash it onto the stored prefix
            # instead of rescanning every action behind it: this is the state
            # every sync and undo lands in while the drawer holds the pen.
            previous = self.hashes[-1] if self.hashes else HISTORY_HASH_INITIAL
            return extend_history_hash(previous, self.history.record_bytes(-1))
        return canvas_history_hash(self.history)

    def _finalize_history_action(self) -> None:
        if not self.history:
            return
        expected_prefixes = len(self.history) - 1
        if len(self.hashes) != expected_prefixes:
            self.hashes.clear()
            value = HISTORY_HASH_INITIAL
            for index in range(len(self.history)):
                value = extend_history_hash(value, self.history.record_bytes(index))
                self.hashes.append(value)
            return
        previous = self.hashes[-1] if self.hashes else HISTORY_HASH_INITIAL
        self.hashes.append(
            extend_history_hash(previous, self.history.record_bytes(-1))
        )

    def commit_sequence(
        self,
        sequence: int,
        mutation: str = "action",
    ) -> tuple[int, int, str]:
        if sequence != self.sequence + 1:
            raise ValueError("canvas sequence is not the next expected value")
        self.sequence = sequence
        commit = (self.revision, self.hash, mutation)
        self.commits.append(commit)
        overflow = len(self.commits) - MAX_CANVAS_COMMITS
        if overflow > 0:
            del self.commits[:overflow]
            self.commit_base_sequence += overflow
        return commit

    def get_commit(self, sequence: int) -> tuple[int, int, str] | None:
        index = sequence - self.commit_base_sequence
        if not 0 <= index < len(self.commits):
            return None
        return self.commits[index]

    def restart_active_path(self) -> bool:
        """Discard an uncommitted path so its semantic action can be replayed."""
        if (
            self.active_path_index is None
            or self.active_path_index != len(self.history) - 1
        ):
            return False
        removed = self.history.pop()
        if removed.tag != PATH_TAG:
            return False
        self.point_count -= removed.point_count
        self.revision -= 1
        del self.hashes[len(self.history):]
        self.active_path_index = None
        return True

    def undo_last_stroke(self) -> bool:
        """Remove the most recent semantic drawing action."""
        if not self.history:
            return False
        self.active_path_index = None
        removed = self.history.pop()
        del self.hashes[len(self.history):]
        if removed.tag == PATH_TAG:
            self.point_count -= removed.point_count
        self.revision += 1
        return True
