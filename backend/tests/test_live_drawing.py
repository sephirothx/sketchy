import pytest

from app.live_drawing import decode_live_drawing, encode_live_drawing


@pytest.mark.parametrize(
    "event,payload,expected_size",
    [
        ("draw_start", {"x": 0.25, "y": 0.75, "color": "#aabbcc", "width": 4}, 9),
        (
            "draw_move",
            {"points": [{"x": 0.1, "y": 0.2}, {"x": 1.2, "y": -0.1}]},
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
