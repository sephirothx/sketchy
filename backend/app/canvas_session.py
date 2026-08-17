"""Per-turn canvas protocol state and drawing-history operations."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.canvas_history import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    CHECKPOINT_TAG,
    CLEAR_TAG,
    FILL_TAG,
    FILL_WORK,
    HISTORY_HASH_INITIAL,
    MAX_CANVAS_POINTS,
    MAX_WINDOW_ACTIONS,
    MAX_WINDOW_WORK,
    PATH_TAG,
    PATH_WORK,
    SHAPE_TAG,
    PackedCanvasHistory,
    action_replay_work,
    canvas_history_hash,
    color_to_int,
    extend_history_hash,
    needed_fold_count,
    validate_checkpoint_png,
)


# The browser retains at most 256 unacknowledged mutations. Keeping twice that
# window lets the server answer ordinary duplicate deliveries without allowing
# per-turn acknowledgement state to grow with the sequence number forever.
MAX_CANVAS_COMMITS = 512

# Re-export so existing tests can monkeypatch the session module.
MAX_CANVAS_ACTIONS = MAX_WINDOW_ACTIONS


def _fold_label(needed: int | None) -> str:
    if needed is None:
        return "ok"
    if needed < 0:
        return "blocked"
    return f"fold {needed}"


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
    replay_work: int = field(default=0, repr=False, compare=False)
    reject_reason: str | None = field(default=None, repr=False, compare=False)

    def _foldable_count(self) -> int:
        semantic = self.history.semantic_count()
        if self.active_path_index is None:
            return semantic
        return max(0, semantic - 1)

    def needed_fold_count(
        self,
        *,
        extra_work: int = 0,
        extra_points: int = 0,
        extra_actions: int = 0,
    ) -> int | None:
        return needed_fold_count(
            self.history,
            extra_work=extra_work,
            extra_points=extra_points,
            extra_actions=extra_actions,
            foldable_count=self._foldable_count(),
        )

    def window_needs_compact(self, threshold: float = 0.8) -> int | None:
        """Fold count to bring the live window under `threshold` of every cap."""
        target_work = int(MAX_WINDOW_WORK * threshold)
        target_actions = max(1, int(MAX_WINDOW_ACTIONS * threshold))
        target_points = int(MAX_CANVAS_POINTS * threshold)
        return needed_fold_count(
            self.history,
            extra_work=MAX_WINDOW_WORK - target_work,
            extra_points=MAX_CANVAS_POINTS - target_points,
            extra_actions=MAX_WINDOW_ACTIONS - target_actions,
            foldable_count=self._foldable_count(),
        )

    def debug_summary(self) -> str:
        """One-line replay-window usage for server logs."""
        work = self.replay_work
        actions = self.history.semantic_count()
        points = self.point_count
        png_bytes = self.history.checkpoint_png_size()
        ratios = (
            ("work", work / MAX_WINDOW_WORK if MAX_WINDOW_WORK else 0),
            ("actions", actions / MAX_WINDOW_ACTIONS if MAX_WINDOW_ACTIONS else 0),
            ("points", points / MAX_CANVAS_POINTS if MAX_CANVAS_POINTS else 0),
        )
        hottest, hottest_ratio = max(ratios, key=lambda item: item[1])
        return (
            f"work={work}/{MAX_WINDOW_WORK} ({work / MAX_WINDOW_WORK:.0%}) "
            f"actions={actions}/{MAX_WINDOW_ACTIONS} ({actions / MAX_WINDOW_ACTIONS:.0%}) "
            f"points={points}/{MAX_CANVAS_POINTS} ({points / MAX_CANVAS_POINTS:.0%}) "
            f"png={png_bytes}B hottest={hottest}@{hottest_ratio:.0%} "
            f"compact80={_fold_label(self.window_needs_compact())} "
            f"next_fill={_fold_label(self.needed_fold_count(extra_work=FILL_WORK, extra_points=0, extra_actions=1))} "
            f"next_stroke={_fold_label(self.needed_fold_count(extra_work=PATH_WORK, extra_points=1, extra_actions=1))}"
        )

    def apply_checkpoint(self, png: bytes, folded_count: int, prefix_hash: int) -> str | None:
        """Replace the folded semantic prefix with a PNG. Returns a reject reason or None."""
        self.reject_reason = None
        try:
            validate_checkpoint_png(png)
        except ValueError:
            self.reject_reason = "checkpoint"
            return self.reject_reason
        foldable = self._foldable_count()
        if folded_count < 1 or folded_count > foldable:
            self.reject_reason = "checkpoint"
            return self.reject_reason
        prefix_index = self.history.semantic_start() + folded_count - 1
        if prefix_index >= len(self.hashes) or self.hashes[prefix_index] != prefix_hash:
            self.reject_reason = "checkpoint"
            return self.reject_reason
        had_active_path = self.active_path_index is not None
        folded_work = 0
        folded_points = 0
        start = self.history.semantic_start()
        for index in range(start, start + folded_count):
            tag = self.history.tag_at(index)
            folded_work += action_replay_work(tag)
            if tag == PATH_TAG:
                record = self.history.record_bytes(index)
                folded_points += (len(record) - 5) // 4
        self.history.compact_prefix(png, folded_count)
        self.replay_work -= folded_work
        self.point_count -= folded_points
        if had_active_path:
            self.active_path_index = len(self.history) - 1
        self.revision += 1
        self._rebuild_hashes()
        return None

    def record_stroke(self, event: str, payload: dict) -> bool:
        self.reject_reason = None
        if self.history.last_is_clear():
            if event == "clear_canvas":
                return True
            self.history.clear()
            self.hashes.clear()
            self.active_path_index = None
            self.point_count = 0
            self.replay_work = 0
        if event == "draw_move":
            if self.active_path_index is None:
                self.reject_reason = "invalid"
                return False
            extra_points = len(payload["points"])
            if self.point_count + extra_points > MAX_CANVAS_POINTS:
                self.reject_reason = "point_count"
                return False
            self.history.extend_path(
                self.active_path_index,
                [(point["x"], point["y"]) for point in payload["points"]],
            )
            self.point_count += extra_points
            return True
        if event == "draw_end":
            if self.active_path_index is None:
                self.reject_reason = "invalid"
                return False
            self.active_path_index = None
            self._finalize_history_action()
            return True
        extra_work, extra_points, extra_actions = self._prospective_cost(event)
        if extra_actions < 0:
            self.reject_reason = "invalid"
            return False
        needed = self.needed_fold_count(
            extra_work=extra_work,
            extra_points=extra_points,
            extra_actions=extra_actions,
        )
        if needed == -1:
            if extra_work and self.replay_work + extra_work > MAX_WINDOW_WORK:
                self.reject_reason = "replay_work"
            elif extra_points and self.point_count + extra_points > MAX_CANVAS_POINTS:
                self.reject_reason = "point_count"
            else:
                self.reject_reason = "action_count"
            return False
        if needed:
            # Client must compact first; do not accept an over-budget action.
            if extra_work and self.replay_work + extra_work > MAX_WINDOW_WORK:
                self.reject_reason = "replay_work"
            elif extra_points and self.point_count + extra_points > MAX_CANVAS_POINTS:
                self.reject_reason = "point_count"
            else:
                self.reject_reason = "action_count"
            return False
        self.active_path_index = None
        if event == "draw_start":
            self.active_path_index = self.history.append_path(
                [(payload["x"], payload["y"])],
                color=color_to_int(payload["color"]),
                width=payload["width"],
            )
            self.point_count += 1
            self.replay_work += PATH_WORK
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
            self.replay_work += action_replay_work(SHAPE_TAG)
        elif event == "draw_fill":
            self.history.append_fill(
                x=min(CANVAS_WIDTH - 1, int(payload["x"] * CANVAS_WIDTH)),
                y=min(CANVAS_HEIGHT - 1, int(payload["y"] * CANVAS_HEIGHT)),
                color=color_to_int(payload["color"]),
            )
            self.replay_work += action_replay_work(FILL_TAG)
        else:
            self.reject_reason = "invalid"
            return False
        self.revision += 1
        self._finalize_history_action()
        return True

    def clear_canvas_stroke(self) -> bool:
        """Record a clear action so Undo can restore the preceding history."""
        self.reject_reason = None
        if not self.history or self.history.last_is_clear():
            self.reject_reason = "invalid"
            return False
        if self.history.last_is_checkpoint() and self.history.semantic_count() == 0:
            # A checkpoint-only history still has pixels to clear.
            pass
        needed = self.needed_fold_count(extra_work=0, extra_points=0, extra_actions=1)
        if needed == -1 or needed:
            self.reject_reason = "action_count"
            return False
        self.active_path_index = None
        self.history.append_clear()
        self.replay_work += action_replay_work(CLEAR_TAG)
        self.revision += 1
        self._finalize_history_action()
        return True

    def sync_payload(self) -> bytes:
        return self.history.binary_payload()

    @property
    def hash(self) -> int:
        if len(self.hashes) == len(self.history):
            return self.hashes[-1] if self.hashes else HISTORY_HASH_INITIAL
        return canvas_history_hash(self.history)

    def _prospective_cost(self, event: str) -> tuple[int, int, int]:
        if event == "draw_start":
            return PATH_WORK, 1, 1
        if event == "draw_shape":
            return action_replay_work(SHAPE_TAG), 0, 1
        if event == "draw_fill":
            return action_replay_work(FILL_TAG), 0, 1
        return -1, 0, -1

    def _rebuild_hashes(self) -> None:
        self.hashes.clear()
        value = HISTORY_HASH_INITIAL
        for index in range(len(self.history)):
            value = extend_history_hash(value, self.history.record_bytes(index))
            self.hashes.append(value)

    def _finalize_history_action(self) -> None:
        if not self.history:
            return
        expected_prefixes = len(self.history) - 1
        if len(self.hashes) != expected_prefixes:
            self._rebuild_hashes()
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
        self.replay_work -= removed.work_units
        self.revision -= 1
        del self.hashes[len(self.history):]
        self.active_path_index = None
        return True

    def undo_last_stroke(self) -> bool:
        """Remove the most recent semantic drawing action. Cannot undo a checkpoint."""
        if not self.history or self.history.last_is_checkpoint():
            return False
        self.active_path_index = None
        removed = self.history.pop()
        if removed.tag == CHECKPOINT_TAG:
            # Restore the checkpoint we accidentally popped.
            return False
        del self.hashes[len(self.history):]
        if removed.tag == PATH_TAG:
            self.point_count -= removed.point_count
        self.replay_work -= removed.work_units
        self.revision += 1
        return True
