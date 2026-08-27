"""Per-turn canvas protocol state and drawing-history operations."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.canvas_history import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    HISTORY_HASH_INITIAL,
    MAX_CANVAS_ACTIONS,
    MAX_CANVAS_POINTS,
    CLEAR_TAG,
    FILL_TAG,
    PATH_TAG,
    SHAPE_TAG,
    PackedCanvasHistory,
    canvas_history_hash,
    color_to_int,
    extend_history_hash,
)


# The browser retains at most 256 unacknowledged mutations. Keeping twice that
# window lets the server answer ordinary duplicate deliveries without allowing
# per-turn acknowledgement state to grow with the sequence number forever.
MAX_CANVAS_COMMITS = 512

# What each action costs to replay, relative to a path. Every client that
# joins or resynchronizes replays the whole turn, so this is other people's
# time, not the drawer's - which is what makes an unbounded turn a way to
# grief a room rather than merely a way to waste a server.
#
# A fill repaints all 480,000 pixels in the worst case, against a fraction of
# them for a path or a shape; 200 is the ratio measured in Chromium (6.1ms
# against ~0.02ms). The cost is a constant because the server never
# rasterizes: it cannot tell a fill bounded by surrounding strokes, which is
# what real fills are, from one flooding an empty canvas.
REPLAY_WORK_BY_TAG = {PATH_TAG: 1, SHAPE_TAG: 1, FILL_TAG: 200, CLEAR_TAG: 0}
REPLAY_WORK_BY_EVENT = {
    "draw_start": REPLAY_WORK_BY_TAG[PATH_TAG],
    "draw_shape": REPLAY_WORK_BY_TAG[SHAPE_TAG],
    "draw_fill": REPLAY_WORK_BY_TAG[FILL_TAG],
}

# Roughly a hundred worst-case fills: about 2.4s of replay on a
# four-times-throttled mobile client, against the eight minutes an unbounded
# turn of fills used to cost. Cheap actions cannot reach it - MAX_CANVAS_ACTIONS
# binds first - so in practice this is a fill budget.
#
# The client greys the fill tool out before the budget can run down (see
# `canvasReplayWork` in the frontend), so a drawer meets this as a disabled
# button rather than as a refusal. This value is the authoritative backstop for
# a client that does not, and the client is deliberately the stricter of the two.
MAX_TURN_REPLAY_WORK = 20_000


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

    def record_stroke(self, event: str, payload: dict) -> bool:
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
        cost = REPLAY_WORK_BY_EVENT.get(event, 0)
        if self.replay_work + cost > MAX_TURN_REPLAY_WORK:
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
            self.replay_work += cost
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
        self.replay_work += cost
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

    def sync_payload(self, start: int = 0) -> bytes:
        return self.history.binary_payload(start)

    def committed_prefix_matches(self, count: int, history_hash: int) -> bool:
        """Whether this session's first `count` actions hash to `history_hash`.

        O(1): `hashes` is already a prefix array, so a client's claim about
        what it holds is checked by one lookup rather than by rehashing.

        Deliberately refuses to validate inside an open path. `hashes` holds
        one entry per *finalized* action, so while the drawer holds the pen the
        history is one longer than the prefix array - and the hash of a record
        still being appended to is not something a client could have committed
        to. Refusing there costs a full sync in the rarest case and keeps this
        from ever answering about a moving target.
        """
        if not 0 <= count <= len(self.hashes):
            return False
        expected = HISTORY_HASH_INITIAL if count == 0 else self.hashes[count - 1]
        return expected == history_hash

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
        self._refund_replay_work(removed.tag)
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
        self._refund_replay_work(removed.tag)
        self.revision += 1
        return True

    def _refund_replay_work(self, tag: int) -> None:
        """Hand back what a removed action was charged.

        Undo takes the action out of the history, so it takes it out of what
        every joining client has to replay too - a drawer who undoes a fill
        should get that budget back rather than being held to a turn they
        walked away from.
        """
        self.replay_work = max(
            0, self.replay_work - REPLAY_WORK_BY_TAG.get(tag, 0)
        )
