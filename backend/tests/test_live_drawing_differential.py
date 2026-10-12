"""The server's live-drawing decoder against the client's, over generated frames (#1464).

The server checks a drawer's frame with `decode_live_drawing` and then forwards
the drawer's own bytes to every viewer (`_rebroadcast` in
`app/handlers/drawing.py`), where `decodeLiveDrawing` in
`frontend/src/lib/liveDrawing.ts` reads them. Nothing re-encodes in between. So
the two decoders have to agree on every frame: one the server accepts that a
viewer refuses or reads differently puts a stroke in the room's history that
the viewer never drew - and a drawer can send such a frame on purpose. The
shared fixtures pin a handful of frames both sides wrote; this compares the
decoders on frames neither side wrote.

Frames are built **record by record** rather than by flipping bytes. A spike
over 200k byte-mutated frames found no disagreement, and when the client's
upper range check was removed on purpose it found that only 7 times in 200k:
the interesting frames are the ones whose structure is nearly right, with a
coordinate on the range edge or a width marker in an odd place, and random
bytes almost never are. Each frame is then optionally truncated, extended or
bit-flipped, so the refusal paths are compared too.

Every frame is compared in each shape it can cross the wire in (R-ENG-20).
As bytes - handed to the client both as a `Uint8Array` and as the
`ArrayBuffer` socket.io-client delivers - as the canonical base64 string small
frames travel as, and as the bare integer of a control action, the two sides
must agree on *whether* it decodes as well as on what to. The base64 string is
also sent loosely written: unpadded, with a line break, with non-zero padding
bits. There the property is one-way, because the client's `atob` is lenient by
design and accepts strings the server refuses - which the server then never
relays - so what is asserted is the half that matters: every string the server
accepts, the client decodes to the same packet. A relative frame is resolved
against the same predecessor on both sides, as the server and a viewer each
resolve it against the open path's last point.

The client runs as one Node process for the whole module
(`live_drawing_oracle.mjs`), so a generated frame costs a pipe round trip
rather than a process. Budgets and reproducibility: `tests/fuzzing.py`.
"""
from __future__ import annotations

import base64
import json
import queue
import shutil
import subprocess
import threading
from collections import Counter, deque
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.canvas_history import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    COORDINATE_SCALE,
    MAX_PACKED_COORDINATE,
    MIN_PACKED_COORDINATE,
)
from app.live_drawing import (
    CLEAR_TAG,
    FILL_TAG,
    LIVE_DRAWING_VERSION,
    MAX_POINTS_PER_FRAME,
    PATH_END_TAG,
    PATH_POINTS_DELTA_TAG,
    PATH_POINTS_END_TAG,
    PATH_POINTS_RELATIVE_TAG,
    PATH_POINTS_TAG,
    PATH_START_TAG,
    SHAPE_TAG,
    decode_live_drawing,
    is_relative,
    resolve_relative_points,
)
from tests.fuzzing import budget, stall_guard

pytestmark = pytest.mark.fuzz

ORACLE = Path(__file__).with_name("live_drawing_oracle.mjs")
# Far beyond any real answer, which takes well under a millisecond. A decoder
# that loops forever on some frame fails with the frame named, rather than
# holding the CI job until the runner gives up hours later.
ANSWER_SECONDS = 3
STARTUP_SECONDS = 60
TAGS = {
    PATH_START_TAG: "path_start",
    PATH_POINTS_TAG: "path_points",
    PATH_END_TAG: "path_end",
    SHAPE_TAG: "shape",
    FILL_TAG: "fill",
    CLEAR_TAG: "clear",
    PATH_POINTS_DELTA_TAG: "path_points_delta",
    PATH_POINTS_RELATIVE_TAG: "path_points_relative",
    PATH_POINTS_END_TAG: "path_points_end",
}

# --- The client, as a process ----------------------------------------------------


class OracleFailure(Exception):
    """The client's process failed to answer: it hung, exited or wrote
    something that is not an answer. A finding about the frame that caused it,
    not a disagreement to shrink."""


class Oracle:
    def __init__(self) -> None:
        self._node = shutil.which("node")
        if self._node is None:
            # Not a skip: a comparison that quietly does not run is the failure
            # this suite exists to prevent. The backend CI job installs Node
            # for it.
            pytest.fail("node is not on PATH; the live-drawing differential needs Node 22.12+")
        self._start()
        # One request before any frame, so a Node that cannot run the module
        # fails once, with its own error, instead of inside the first generated
        # example. Given longer than a frame: this one includes starting Node
        # and stripping the module's types on a busy CI runner.
        try:
            self.decode([{"int": 0x12, "previous": None}], what="the start-up check", seconds=STARTUP_SECONDS)
        except OracleFailure as error:
            self.close()
            pytest.fail(str(error))

    def _start(self) -> None:
        self._process = subprocess.Popen(
            # The flag is a no-op on a Node that strips types by default.
            [self._node, "--experimental-strip-types", "--no-warnings", str(ORACLE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Both pipes are read on threads: stdout so every answer can be waited
        # for with a deadline, stderr so a decoder that writes to it cannot
        # fill the pipe and block (Node writes pipes synchronously on Linux),
        # and so a crash can be reported with what it said. A process gets its
        # own queue, so nothing a replaced one wrote late is read as an answer.
        self._answers: queue.Queue[str] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=40)
        threading.Thread(target=self._pump, args=(self._process.stdout, self._answers.put, True), daemon=True).start()
        threading.Thread(target=self._pump, args=(self._process.stderr, self._stderr.append, False), daemon=True).start()

    @staticmethod
    def _pump(stream, sink, mark_end: bool) -> None:
        for line in stream:
            sink(line)
        if mark_end:
            sink("")

    def _replace(self, reason: str) -> OracleFailure:
        """Put a fresh process in place of a failed one, and say what failed."""
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait()
        said = "".join(self._stderr).strip()
        self._start()
        return OracleFailure(f"{reason}{': ' + said if said else ''}")

    def decode(self, requests: list[dict], *, what: str, seconds: float = ANSWER_SECONDS) -> list[dict]:
        assert self._process.stdin
        try:
            self._process.stdin.write(json.dumps(requests) + "\n")
            self._process.stdin.flush()
            line = self._answers.get(timeout=seconds)
        except BrokenPipeError:
            line = ""
        except queue.Empty:
            raise self._replace(f"the Node decoder gave no answer in {seconds} s for {what}") from None
        if not line:
            raise self._replace(f"the Node decoder exited on {what}")
        try:
            answers = json.loads(line)
        except json.JSONDecodeError:
            raise self._replace(f"the Node decoder wrote something that is not an answer for {what}: {line[:200]!r}") from None
        if len(answers) != len(requests):
            raise self._replace(f"the Node decoder gave {len(answers)} answers to {len(requests)} requests for {what}")
        return answers

    def close(self) -> None:
        try:
            if self._process.stdin:
                self._process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()


@pytest.fixture(scope="module")
def oracle():
    process = Oracle()
    yield process
    process.close()


# --- The server, normalized to the same shape -----------------------------------


def _python_decode(wire, previous: tuple[float, float]):
    """What the server makes of `wire`: the packet it would record and relay,
    or None for one it refuses - including a relative frame whose walk from the
    open path's last point leaves the packed range, which the handler refuses."""
    try:
        packet = decode_live_drawing(wire)
        if is_relative(packet):
            packet = resolve_relative_points(packet, previous)
    except ValueError:
        return None
    out: dict = {"event": packet.event}
    for key, value in packet.payload.items():
        if key == "points":
            out[key] = [[point["x"], point["y"]] for point in value]
        elif key in ("from", "to"):
            out[key] = [value["x"], value["y"]]
        else:
            out[key] = value
    # Through JSON, as the client's answer came: tuples become lists, and a
    # float is compared as the double both languages parse it to.
    return json.loads(json.dumps(out))


# --- Frames, record by record ----------------------------------------------------

_int16 = st.one_of(
    st.sampled_from([
        -(2**15), MIN_PACKED_COORDINATE, MIN_PACKED_COORDINATE + 1, -1, 0, 1,
        CANVAS_WIDTH * COORDINATE_SCALE - 1, CANVAS_WIDTH * COORDINATE_SCALE,
        CANVAS_HEIGHT * COORDINATE_SCALE, MAX_PACKED_COORDINATE - 1, MAX_PACKED_COORDINATE,
    ]),
    st.integers(-(2**15), 2**15 - 1),
)
_int8 = st.one_of(st.sampled_from([-128, -127, -126, -1, 0, 1, 126, 127]), st.integers(-128, 127))
_width = st.one_of(st.sampled_from([0, 1, 2, 63, 64, 65, 128, 255]), st.integers(0, 255))
_color = st.binary(min_size=3, max_size=3)


def _i16(value: int) -> bytes:
    return value.to_bytes(2, "little", signed=True)


def _i8_pair(first: int, second: int) -> bytes:
    return first.to_bytes(1, "little", signed=True) + second.to_bytes(1, "little", signed=True)


_point = st.builds(lambda x, y: _i16(x) + _i16(y), _int16, _int16)
# The records an offset frame is made of. A delta is written as raw signed
# bytes, so its first byte can itself be the escape or width marker - which an
# encoder never writes and a peer can. Two width markers side by side get a
# record of their own: both decoders must refuse them, and two separately
# drawn records almost never land adjacent with everything around them valid.
_record = st.one_of(
    st.builds(_i8_pair, _int8, _int8),
    st.builds(lambda point: b"\x80" + point, _point),
    st.builds(lambda width: b"\x81" + bytes((width,)), _width),
    st.builds(lambda a, b: b"\x81" + bytes((a,)) + b"\x81" + bytes((b,)), st.integers(1, 64), st.integers(1, 64)),
)

# Long runs are built from records that are each well-formed - points inside
# the packed range, steps that cannot be read as a marker, a width change only
# ever followed by its point - because 250 freely drawn records essentially
# always contain one bad one, and a frame at the point limit would then never
# be accepted. The range edges stay in, and the frame-level mutation in
# `frames` is what breaks these.
_coordinate = st.one_of(
    st.sampled_from([MIN_PACKED_COORDINATE, 0, MAX_PACKED_COORDINATE]),
    st.integers(MIN_PACKED_COORDINATE, MAX_PACKED_COORDINATE),
)
_valid_point = st.builds(lambda x, y: _i16(x) + _i16(y), _coordinate, _coordinate)
_step = st.builds(_i8_pair, st.integers(-4, 4), st.integers(-4, 4))
_valid_record = st.one_of(
    _step,
    _step,
    st.builds(lambda point: b"\x80" + point, _valid_point),
    st.builds(lambda width, step: b"\x81" + bytes((width,)) + step, st.integers(1, 64), _step),
)


@st.composite
def _long_run(draw, valid_element, element) -> bytes:
    """A well-formed run straddling the per-frame point limit (the delta
    frame's first point makes 255 records a full frame): a short drawn pattern
    tiled out to length, which costs a handful of draws instead of 256 and
    still shrinks. Now and then one record anywhere in it is replaced by an
    arbitrary one, so a single bad record deep in a long frame is compared too."""
    pattern = draw(st.lists(valid_element, min_size=1, max_size=6))
    length = draw(st.integers(MAX_POINTS_PER_FRAME - 2, MAX_POINTS_PER_FRAME + 1))
    run = (pattern * (length // len(pattern) + 1))[:length]
    if draw(st.integers(0, 3)) == 0:
        run[draw(st.integers(0, length - 1))] = draw(element)
    return b"".join(run)


def _counted(element, valid_element):
    """A short run of anything, or a long well-formed one."""
    return st.one_of(
        st.lists(element, max_size=12).map(b"".join),
        st.lists(element, max_size=12).map(b"".join),
        _long_run(valid_element, element),
    )


_BODIES = {
    PATH_START_TAG: st.builds(lambda c, w, p: c + bytes((w,)) + p, _color, _width, _point),
    PATH_POINTS_TAG: _counted(_point, _valid_point),
    PATH_END_TAG: st.just(b""),
    SHAPE_TAG: st.builds(
        lambda shape, c, w, a, b: bytes((shape,)) + c + bytes((w,)) + a + b,
        st.integers(0, 5), _color, _width, _point, _point,
    ),
    FILL_TAG: st.builds(
        lambda c, x, y: c + x.to_bytes(2, "little") + y.to_bytes(2, "little"),
        _color,
        st.one_of(st.sampled_from([0, CANVAS_WIDTH - 1, CANVAS_WIDTH, 65535]), st.integers(0, 65535)),
        st.one_of(st.sampled_from([0, CANVAS_HEIGHT - 1, CANVAS_HEIGHT, 65535]), st.integers(0, 65535)),
    ),
    CLEAR_TAG: st.just(b""),
    PATH_POINTS_DELTA_TAG: st.builds(lambda first, rest: first + rest, _point, _counted(_record, _valid_record)),
    PATH_POINTS_RELATIVE_TAG: _counted(_record, _valid_record),
    PATH_POINTS_END_TAG: _counted(_record, _valid_record),
}

# Known tags most of the time; the seven unassigned ones and a wrong version
# now and then.
_tag = st.sampled_from([*TAGS] * 4 + list(range(9, 16)))
_version = st.sampled_from([LIVE_DRAWING_VERSION] * 12 + [0, 2, 15])


@st.composite
def frames(draw) -> bytes:
    if draw(st.integers(0, 19)) == 0:
        return draw(st.binary(max_size=40))
    tag = draw(_tag)
    body = draw(_BODIES.get(tag, st.binary(max_size=16)))
    frame = bytes(((draw(_version) << 4) | tag,)) + body
    mutation = draw(st.sampled_from(["none"] * 6 + ["truncate", "extend", "flip"]))
    if mutation == "truncate" and len(frame) > 1:
        frame = frame[: draw(st.integers(1, len(frame) - 1))]
    elif mutation == "extend":
        frame += draw(st.binary(min_size=1, max_size=6))
    elif mutation == "flip":
        index = draw(st.integers(0, len(frame) - 1))
        frame = frame[:index] + bytes((frame[index] ^ (1 << draw(st.integers(0, 7))),)) + frame[index + 1 :]
    return frame


# The open path's last point, as both histories keep it: a packed value turned
# back into a normalized coordinate.
_previous = st.builds(
    lambda x, y: (x / (CANVAS_WIDTH * COORDINATE_SCALE), y / (CANVAS_HEIGHT * COORDINATE_SCALE)),
    _coordinate,
    _coordinate,
)

# Frames that once told the two decoders apart, or would: a delta walk past the
# top of the packed range (the client's upper bound, removed in the spike), the
# same walk from an escape record sitting on the edge, and two width markers
# side by side (a pending-marker check, removed in review).
_EDGE_WALK = bytes((0x16,)) + _i16(MAX_PACKED_COORDINATE) + _i16(0) + b"\x01\x00"
_ESCAPE_THEN_WALK = bytes((0x17,)) + b"\x80" + _i16(MAX_PACKED_COORDINATE) + _i16(0) + b"\x01\x00"
_TWO_WIDTHS = bytes((0x17,)) + b"\x81\x01\x81\x02\x00\x00"

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _loose_base64(text: str) -> list[str]:
    """The canonical string written the ways a peer might, and `atob` takes:
    without its padding, broken by a newline, and with the padding bits that
    canonical base64 leaves zero set instead."""
    variants = [text.rstrip("="), text[: len(text) // 2] + "\n" + text[len(text) // 2 :]]
    padding = len(text) - len(text.rstrip("="))
    if padding:
        last = len(text) - padding - 1
        variants.append(text[:last] + _B64[_B64.index(text[last]) | 1] + text[last + 1 :])
    return [variant for variant in variants if variant != text]


def _shapes(frame: bytes) -> list[tuple[str, object, dict, bool]]:
    """`frame` in every shape it can cross the wire in, as (name, what Python
    receives, what Node receives, whether refusals must agree too)."""
    text = base64.b64encode(frame).decode()
    shapes = [
        ("binary", frame, {"hex": frame.hex()}, True),
        ("ArrayBuffer", frame, {"buffer": frame.hex()}, True),
        ("base64", text, {"b64": text}, True),
    ]
    shapes += [("loose base64", loose, {"b64": loose}, False) for loose in _loose_base64(text)]
    if len(frame) == 1:
        shapes.append(("integer", frame[0], {"int": frame[0]}, True))
    return shapes


def test_both_decoders_agree_on_every_generated_frame(oracle):
    seen: Counter = Counter()
    # The first frame the client's process failed on, if any. Kept out of
    # Hypothesis on purpose: shrinking it would cost a timeout or a restart
    # per attempt - minutes, for a hang - and the frame is already exact.
    broke: list[str] = []

    @settings(max_examples=budget(3000))
    @example(frame=_EDGE_WALK, previous=(0.5, 0.5))
    @example(frame=_ESCAPE_THEN_WALK, previous=(0.5, 0.5))
    @example(frame=_TWO_WIDTHS, previous=(0.5, 0.5))
    @given(frame=frames(), previous=_previous)
    def check(frame: bytes, previous: tuple[float, float]):
        if broke:
            return
        shapes = _shapes(frame)
        try:
            answers = oracle.decode(
                [{**request, "previous": list(previous)} for _, _, request, _ in shapes],
                what=f"frame {frame.hex()} from previous {previous}",
            )
        except OracleFailure as failure:
            broke.append(str(failure))
            return
        for (shape, wire, _, both_ways), answer in zip(shapes, answers, strict=True):
            expected = _python_decode(wire, previous)
            assert "threw" not in answer, (
                f"the client threw on a {shape} frame instead of refusing it: "
                f"{answer['threw']} (frame {frame.hex()})"
            )
            if expected is None and not both_ways:
                # The server refuses it, so no viewer ever receives it.
                continue
            assert answer["result"] == expected, (
                f"the decoders disagree on a {shape} frame {frame.hex()} "
                f"from previous {previous}:\n  server: {expected}\n  client: {answer['result']}"
            )
            if shape == "binary":
                tag = TAGS.get(frame[0] & 0x0F) if frame else None
                seen[(tag, expected is not None)] += 1
                if expected is not None and len(expected.get("points", ())) == MAX_POINTS_PER_FRAME:
                    seen["full_frame"] += 1
                if expected is not None and expected.get("widths"):
                    seen["widths"] += 1

    with stall_guard():
        check()
    if broke:
        pytest.fail(broke[0])

    # A generator that drifts into producing only refused frames would pass
    # the comparison while comparing nothing. Every frame kind has to be
    # reached both accepted and refused, frames at the point limit have to be
    # accepted, and so do width changes.
    for name in TAGS.values():
        assert seen[(name, True)] >= 5, (name, dict(seen))
        assert seen[(name, False)] >= 5, (name, dict(seen))
    assert seen["full_frame"] >= 10, dict(seen)
    assert seen["widths"] >= 20, dict(seen)
