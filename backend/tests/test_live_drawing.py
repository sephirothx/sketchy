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
