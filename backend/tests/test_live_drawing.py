import pytest

from app.live_drawing import decode_live_drawing, encode_live_drawing


@pytest.mark.parametrize(
    "event,payload,expected_size",
    [
        ("draw_start", {"x": 0.25, "y": 0.75, "color": "#aabbcc", "width": 4}, 9),
        # A whole canvas apart, so delta coding would need an escape and come
        # out larger. The encoder picks absolute instead - the fallback that
        # keeps this change from ever costing more than it saves.
        (
            "draw_move",
            {"points": [{"x": 0.1, "y": 0.2}, {"x": 1.2, "y": -0.1}]},
            9,
        ),
        # The ordinary case: adjacent pointer samples, two bytes per point
        # after the first, which is where the volume actually is.
        (
            "draw_move",
            {
                "points": [
                    {"x": 0.1, "y": 0.2},
                    {"x": 0.105, "y": 0.205},
                    {"x": 0.11, "y": 0.21},
                ]
            },
            9,
        ),
        ("draw_end", {}, None),
        (
            "draw_shape",
            {
                "shape": "ellipse",
                "from": {"x": 0.1, "y": 0.2},
                "to": {"x": 0.8, "y": 0.9},
                "color": "#123456",
                "width": 64,
            },
            14,
        ),
        ("draw_fill", {"x": 0.25, "y": 0.75, "color": "#fedcba"}, 8),
        ("clear_canvas", {}, None),
    ],
)
def test_live_drawing_round_trip(event, payload, expected_size):
    encoded = encode_live_drawing(event, payload)
    decoded = decode_live_drawing(encoded)

    if expected_size is None:
        assert isinstance(encoded, int)
    else:
        assert len(encoded) == expected_size
    assert decoded.event == event
    if "color" in payload:
        assert decoded.payload["color"] == payload["color"]


def test_live_path_coordinates_use_canvas_quarter_pixel_precision():
    packet = decode_live_drawing(
        encode_live_drawing(
            "draw_start",
            {"x": 0.123456, "y": 0.654321, "color": "#000000", "width": 2},
        )
    )

    assert packet.payload["x"] == pytest.approx(round(0.123456 * 800 * 4) / (800 * 4))
    assert packet.payload["y"] == pytest.approx(round(0.654321 * 600 * 4) / (600 * 4))


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        b"",
        b"\x20",
        b"\x1f",
        b"\x10\x00",
        b"\x11",
        0x10,
        0x22,
        True,
        bytes((0x13, 9)) + bytes(12),
        bytes((0x14,)) + bytes(3) + b"\x20\x03\x00\x00",
        bytes((0x15, 0)),
    ],
)
def test_live_drawing_decoder_rejects_malformed_frames(payload):
    with pytest.raises(ValueError):
        decode_live_drawing(payload)


def test_encoder_rejects_invalid_values():
    with pytest.raises(ValueError):
        encode_live_drawing(
            "draw_start",
            {"x": 0.5, "y": 0.5, "color": "black", "width": 4},
        )
    with pytest.raises(ValueError):
        encode_live_drawing("draw_move", {"points": []})
    with pytest.raises(ValueError):
        encode_live_drawing(
            "draw_fill",
            {"x": 1, "y": 0.5, "color": "#000000"},
        )


def test_a_relative_frame_is_offsets_from_the_open_path_and_three_bytes_a_point():
    """#559: with the predecessor in hand the frame carries no absolute point at
    all, so the one-point frame a thinned straight stroke sends every flush
    is 3 bytes rather than 5. It does not decode on its own; the resolver
    turns it into points once the caller has looked the predecessor up."""
    from app.live_drawing import is_relative, resolve_relative_points

    previous = {"x": 0.5, "y": 0.5}
    one = encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": previous})
    assert len(one) == 3
    assert one[0] & 0x0F == 7
    packet = decode_live_drawing(one)
    assert is_relative(packet) and "points" not in packet.payload
    resolved = resolve_relative_points(packet, (0.5, 0.5))
    assert resolved.payload == {"points": [{"x": 0.5, "y": 0.51}]}

    # Several points: still two bytes each, chained from one another.
    many = encode_live_drawing(
        "draw_move",
        {"points": [{"x": 0.5, "y": 0.51}, {"x": 0.51, "y": 0.52}, {"x": 0.52, "y": 0.52}], "previous": previous},
    )
    assert len(many) == 1 + 3 * 2
    assert resolve_relative_points(decode_live_drawing(many), (0.5, 0.5)).payload["points"] == [
        {"x": 0.5, "y": 0.51}, {"x": 0.51, "y": 0.52}, {"x": 0.52, "y": 0.52},
    ]

    # A first point too far from the predecessor would need an escape and
    # make the relative frame the largest form, so it is not taken.
    far = encode_live_drawing("draw_move", {"points": [{"x": 0.9, "y": 0.9}], "previous": previous})
    assert far[0] & 0x0F != 7 and len(far) == 5
    # A later jump inside a relative frame escapes to an absolute pair.
    jump = encode_live_drawing(
        "draw_move", {"points": [{"x": 0.5, "y": 0.51}, {"x": 0.9, "y": 0.9}], "previous": previous},
    )
    assert jump[0] & 0x0F == 7 and len(jump) == 1 + 2 + 5
    assert resolve_relative_points(decode_live_drawing(jump), (0.5, 0.5)).payload["points"][1] == {"x": 0.9, "y": 0.9}

    # Without the predecessor there are no points; the same frame is the
    # same offsets whatever the predecessor turns out to be.
    assert resolve_relative_points(packet, (0.25, 0.25)).payload["points"] == [{"x": 0.25, "y": 0.26}]


@pytest.mark.parametrize(
    "payload",
    [
        bytes((0x17,)),  # no records
        bytes((0x17, 1)),  # half a record
        bytes((0x17, 0x80, 0, 0)),  # an escape with half a pair
        bytes((0x17,)) + bytes((1, 1)) * 257,  # too many points
    ],
)
def test_malformed_relative_frames_are_refused(payload):
    with pytest.raises(ValueError):
        decode_live_drawing(payload)


def test_a_relative_frame_cannot_walk_a_coordinate_out_of_range():
    from app.live_drawing import resolve_relative_points

    packet = decode_live_drawing(bytes((0x17,)) + bytes((127, 0)) * 256)
    with pytest.raises(ValueError):
        # Starting near the right edge of the packed range, 256 steps of 127
        # leave it.
        resolve_relative_points(packet, (1.0, 0.5))


def test_an_ending_batch_is_the_relative_layout_under_its_own_tag():
    """#603: the final points and the end as one frame. Always relative - an
    ending has an open path to be relative to - escaping where a step is too
    far rather than falling back to a self-contained form."""
    from app.live_drawing import ends_path, resolve_relative_points

    previous = {"x": 0.5, "y": 0.5}
    one = encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": previous, "ends": True})
    assert len(one) == 3 and one[0] & 0x0F == 8
    packet = decode_live_drawing(one)
    assert ends_path(packet) and packet.payload["ends"] is True
    resolved = resolve_relative_points(packet, (0.5, 0.5))
    assert resolved.payload == {"points": [{"x": 0.5, "y": 0.51}], "ends": True}
    assert ends_path(resolved)
    far = encode_live_drawing("draw_move", {"points": [{"x": 0.9, "y": 0.9}], "previous": previous, "ends": True})
    assert far[0] & 0x0F == 8 and len(far) == 1 + 5
    assert not ends_path(decode_live_drawing(encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "previous": previous})))
    assert ends_path(decode_live_drawing(encode_live_drawing("draw_end")))
    with pytest.raises(ValueError):
        encode_live_drawing("draw_move", {"points": [{"x": 0.5, "y": 0.51}], "ends": True})
    with pytest.raises(ValueError):
        decode_live_drawing(bytes((0x18,)))


# --- width changes inside a path (#828) -----------------------------------------

PREVIOUS = {"x": 0.5, "y": 0.5}
THREE = [{"x": 0.5, "y": 0.51}, {"x": 0.505, "y": 0.515}, {"x": 0.51, "y": 0.52}]


def test_a_width_change_costs_two_bytes_in_a_frame_already_being_sent():
    from app.live_drawing import resolve_relative_points

    plain = encode_live_drawing("draw_move", {"points": THREE, "previous": PREVIOUS})
    changed = encode_live_drawing(
        "draw_move", {"points": THREE, "previous": PREVIOUS, "widths": [[1, 5]]}
    )

    assert len(changed) == len(plain) + 2
    assert changed[3:5] == bytes((0x81, 5)), "the marker, then the width, in front of the point's record"
    packet = resolve_relative_points(decode_live_drawing(changed), (0.5, 0.5))
    assert packet.payload["widths"] == [(1, 5)]
    assert packet.payload["points"] == resolve_relative_points(
        decode_live_drawing(plain), (0.5, 0.5)
    ).payload["points"]


def test_a_path_that_never_changes_width_is_byte_for_byte_what_it_was():
    for payload in (
        {"points": THREE},
        {"points": THREE, "previous": PREVIOUS},
        {"points": THREE, "previous": PREVIOUS, "ends": True},
    ):
        assert encode_live_drawing("draw_move", payload) == encode_live_drawing(
            "draw_move", {**payload, "widths": []}
        )
        assert "widths" not in decode_live_drawing(encode_live_drawing("draw_move", payload)).payload


def test_a_width_change_without_a_predecessor_rides_the_delta_form():
    frame = encode_live_drawing("draw_move", {"points": THREE, "widths": [[2, 12]]})

    assert frame[0] & 0x0F == 6
    packet = decode_live_drawing(frame)
    assert packet.payload["widths"] == [(2, 12)]
    assert len(packet.payload["points"]) == 3
    # The delta form's first point is not a record, so nothing can sit before it.
    with pytest.raises(ValueError):
        encode_live_drawing("draw_move", {"points": THREE, "widths": [[0, 12]]})


def test_a_frame_with_a_width_change_is_never_absolute_even_when_every_step_is_far():
    far = [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]
    frame = encode_live_drawing("draw_move", {"points": far, "widths": [[1, 3]]})

    assert frame[0] & 0x0F == 6
    assert decode_live_drawing(frame).payload["widths"] == [(1, 3)]


def test_a_step_of_minus_127_escapes_now_that_the_byte_is_the_marker():
    step = 127 / (800 * 4)
    frame = encode_live_drawing(
        "draw_move",
        {"points": [{"x": 0.5, "y": 0.5}, {"x": 0.5 - step, "y": 0.5}], "previous": {"x": 0.5, "y": 0.49}},
    )

    assert frame[3] == 0x80, "escaped to an absolute pair rather than written as 0x81"
    assert "widths" not in decode_live_drawing(frame).payload


@pytest.mark.parametrize(
    "widths",
    [
        [[3, 5]],  # past the batch
        [[-1, 5]],
        [[1, 5], [1, 6]],  # twice on one point
        [[2, 5], [1, 6]],  # out of order
        [[1, 0]],
        [[1, 65]],
        [[1, 5.0]],
        [[True, 5]],
        [[1]],
        "15",
    ],
)
def test_the_encoder_refuses_width_changes_it_cannot_place(widths):
    with pytest.raises(ValueError):
        encode_live_drawing("draw_move", {"points": THREE, "previous": PREVIOUS, "widths": widths})


@pytest.mark.parametrize(
    "payload",
    [
        bytes((0x17, 0x81)),  # a marker with no width
        bytes((0x17, 0x81, 5)),  # a change with no point after it
        bytes((0x17, 1, 1, 0x81, 5)),  # trailing the frame
        bytes((0x17, 0x81, 5, 0x81, 6, 1, 1)),  # two on one point
        bytes((0x17, 0x81, 0, 1, 1)),  # width 0
        bytes((0x17, 0x81, 65, 1, 1)),  # width past the brush's maximum
        bytes((0x18, 0x81, 5)),  # the same, on a final batch
        bytes((0x16, 0, 0, 0, 0, 0x81, 5)),  # and on a delta frame
    ],
)
def test_malformed_width_changes_are_refused(payload):
    with pytest.raises(ValueError):
        decode_live_drawing(payload)


@pytest.mark.parametrize(
    "payload",
    [
        bytes((0x10, 0, 0, 0, 1)) + (-32768).to_bytes(2, "little", signed=True) + bytes(2),
        bytes((0x11,)) + (-32768).to_bytes(2, "little", signed=True) + bytes(2),
        bytes((0x16,)) + (-32768).to_bytes(2, "little", signed=True) + bytes(2),
        bytes((0x17, 0x80)) + (-32768).to_bytes(2, "little", signed=True) + bytes(2),
        bytes((0x13, 0, 0, 0, 0, 1)) + (-32768).to_bytes(2, "little", signed=True) + bytes(6),
    ],
)
def test_no_frame_may_carry_the_coordinate_the_history_reads_as_a_marker(payload):
    """int16's floor as a path x is a width marker in the history, so a point
    there would be recorded as one. It is refused at the door instead, on every
    frame, so the recorder never has to."""
    with pytest.raises(ValueError):
        decode_live_drawing(payload)


def test_the_largest_frame_is_the_relative_one_escaping_and_changing_throughout():
    from app.live_drawing import MAX_FRAME_BYTES, MAX_POINTS_PER_FRAME

    points = [{"x": (i % 2) * 0.999, "y": 0.5} for i in range(MAX_POINTS_PER_FRAME)]
    widths = [[i, 1 + i % 2] for i in range(MAX_POINTS_PER_FRAME)]
    frame = encode_live_drawing("draw_move", {"points": points, "widths": widths, "previous": PREVIOUS})

    assert len(frame) == MAX_FRAME_BYTES == 1 + 256 * 7
    assert len(decode_live_drawing(frame).payload["widths"]) == MAX_POINTS_PER_FRAME
