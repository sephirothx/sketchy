import pytest

from app.canvas_history import (
    ClearAction,
    FillAction,
    MAX_BINARY_CANVAS_HISTORY_BYTES,
    MAX_CANVAS_ACTIONS,
    MAX_CANVAS_POINTS,
    PATH_TAG,
    PackedCanvasHistory,
    PathAction,
    ShapeAction,
    canvas_history_hash,
    color_to_hex,
    color_to_int,
    decode_binary_canvas_history,
)


def representative_actions():
    return [
        PathAction(
            points=[(0.1, 0.2), (0.3, 0.4)],
            color=0xAABBCC,
            width=4,
        ),
        ShapeAction(
            shape="ellipse",
            start=(0.2, 0.3),
            end=(0.8, 0.9),
            color=0x102030,
            width=8,
        ),
        FillAction(x=799, y=599, color=0xFFFFFF),
        ClearAction(),
    ]


def test_packed_canvas_history_uses_fixed_width_binary_records():
    history = PackedCanvasHistory()
    history.append_path(
        [(0.1, 0.2), (0.3, 0.4)],
        color=0xAABBCC,
        width=4,
    )
    history.append_shape(
        shape="ellipse",
        start=(0.2, 0.3),
        end=(0.8, 0.9),
        color=0x102030,
        width=8,
    )
    history.append_fill(x=799, y=599, color=0xFFFFFF)
    history.append_clear()

    # Path header + 2 int16 point pairs, shape, fill, and clear.
    assert len(history.data) == (5 + 2 * 4) + 14 + 8 + 1
    assert history.offsets.itemsize == 4
    assert list(history) == representative_actions()



def test_binary_canvas_history_round_trip_preserves_packed_actions():
    history = PackedCanvasHistory()
    history.append_path([(0.1, 0.2), (0.3, 0.4)], color=0xAABBCC, width=4)
    history.append_shape(
        shape="ellipse",
        start=(0.2, 0.3),
        end=(0.8, 0.9),
        color=0x102030,
        width=8,
    )
    history.append_fill(x=799, y=599, color=0xFFFFFF)
    history.append_clear()

    decoded = decode_binary_canvas_history(history.binary_payload())

    assert decoded == history
    assert decoded.binary_payload() == history.binary_payload()


def test_binary_canvas_history_has_an_exact_theoretical_maximum():
    history = PackedCanvasHistory()
    history.append_path(
        [(0.0, 0.0)] * MAX_CANVAS_POINTS,
        color=0,
        width=1,
    )
    for _ in range(MAX_CANVAS_ACTIONS - 1):
        history.append_shape(
            shape="rectangle",
            start=(0.0, 0.0),
            end=(1.0, 1.0),
            color=0,
            width=1,
        )

    payload = history.binary_payload()

    assert len(payload) == MAX_BINARY_CANVAS_HISTORY_BYTES == 460_002
    assert decode_binary_canvas_history(payload) == history


def test_binary_canvas_history_decoder_rejects_corrupt_envelopes():
    history = PackedCanvasHistory()
    history.append_fill(x=10, y=20, color=0x123456)
    valid = history.binary_payload()

    corrupt_magic = bytearray(valid)
    corrupt_magic[0] = 0
    corrupt_final_offset = bytearray(valid)
    corrupt_final_offset[11:15] = (999).to_bytes(4, "little")
    corrupt_action_tag = bytearray(valid)
    corrupt_action_tag[-8] = 255

    for payload in (
        b"",
        corrupt_magic,
        corrupt_final_offset,
        corrupt_action_tag,
    ):
        with pytest.raises(ValueError):
            decode_binary_canvas_history(payload)


def test_packed_canvas_history_extends_and_pops_a_path_semantically():
    history = PackedCanvasHistory()
    path_index = history.append_path([(0.1, 0.2)], color=0, width=4)
    history.extend_path(path_index, [(0.3, 0.4), (0.5, 0.6)])

    assert len(history.data) == 5 + 3 * 4
    removed = history.pop()
    assert removed.tag == PATH_TAG
    assert removed.point_count == 3
    assert history == []
    assert history.data == bytearray()
    assert len(history.offsets) == 0


def test_canvas_history_crc32_matches_frontend_canonical_encoding():
    history = PackedCanvasHistory()
    history.append_path([(0.1, 0.2), (0.3, 0.4)], color=0xAABBCC, width=4)
    history.append_shape(
        shape="ellipse",
        start=(0.2, 0.3),
        end=(0.8, 0.9),
        color=0x102030,
        width=8,
    )
    history.append_fill(x=799, y=599, color=0xFFFFFF)
    history.append_clear()

    assert canvas_history_hash(history) == 0x0C816F97


def test_the_binary_history_decoder_enforces_the_turn_limits():
    """R-DRAW-07 on the wire decoder itself, not only on storage: a frame
    claiming more actions or points than a turn may hold is refused."""
    too_many_actions = PackedCanvasHistory()
    for _ in range(MAX_CANVAS_ACTIONS + 1):
        too_many_actions.append_clear()
    with pytest.raises(ValueError, match="too many actions"):
        decode_binary_canvas_history(too_many_actions.binary_payload())

    too_many_points = PackedCanvasHistory()
    too_many_points.append_path([(0.0, 0.0)] * (MAX_CANVAS_POINTS + 1), color=0, width=4)
    with pytest.raises(ValueError, match="too many points"):
        decode_binary_canvas_history(too_many_points.binary_payload())


def test_color_encoding_round_trip_preserves_leading_zeroes():
    assert color_to_int("#00a0ff") == 0x00A0FF
    assert color_to_hex(0x00A0FF) == "#00a0ff"
