"""The room's tool and color rules, and the client's copy of them."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.drawing_rules import (
    BLACK_AND_WHITE_COLORS,
    COLORBLIND_SAFE_COLORS,
    COLOR_MODES,
    DEFAULT_ALLOWED_TOOLS,
    DEFAULT_COLOR_MODE,
    DRAWING_TOOLS,
    ERASER_COLOR,
    PALETTE_COLORS,
    allowed_colors,
    check_color_mode,
    clean_allowed_tools,
    color_allowed,
    packet_allowed,
    tool_allowed,
)

FRONTEND_RULES = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "lib" / "drawingRules.ts"
)


def _hexes(source: str, start: str) -> list[str]:
    """The hex colors in the array assigned at `start`, in order."""
    tail = source.split(start, 1)[1]
    return [color.lower() for color in re.findall(r"#[0-9a-fA-F]{6}", tail.split("];", 1)[0])]


def test_the_defaults_take_nothing_away():
    assert set(DEFAULT_ALLOWED_TOOLS) == set(DRAWING_TOOLS)
    assert DEFAULT_COLOR_MODE == "all"
    assert allowed_colors(DEFAULT_COLOR_MODE) is None


@pytest.mark.parametrize(
    "requested,expected",
    [
        (["brush", "fill", "shapes"], ["brush", "fill", "shapes"]),
        # Canonical order, whatever order the client sent
        (["shapes", "brush"], ["brush", "shapes"]),
        (["fill", "brush", "fill"], ["brush", "fill"]),
        (["shapes"], ["shapes"]),
        (["fill", "shapes"], ["fill", "shapes"]),
    ],
)
def test_a_usable_tool_set_is_normalized(requested, expected):
    assert clean_allowed_tools(requested) == expected


@pytest.mark.parametrize("requested", [[], ["fill"], ["brush", "sledgehammer"], "brush", None])
def test_a_set_with_nothing_to_draw_with_is_refused(requested):
    with pytest.raises(ValueError):
        clean_allowed_tools(requested)


def test_the_brush_governs_every_path_event():
    """Erasing is a white brush stroke, so the two are banned or admitted together."""
    for event in ("draw_start", "draw_move", "draw_end"):
        assert tool_allowed(event, ["brush"])
        assert not tool_allowed(event, ["shapes", "fill"])


def test_clearing_the_canvas_is_not_a_tool():
    assert tool_allowed("clear_canvas", ["shapes"])


@pytest.mark.parametrize(
    "event,tool",
    [("draw_shape", "shapes"), ("draw_fill", "fill")],
)
def test_each_remaining_event_answers_to_its_chip(event, tool):
    assert tool_allowed(event, [tool])
    assert not tool_allowed(event, [group for group in DRAWING_TOOLS if group != tool])


@pytest.mark.parametrize("mode", COLOR_MODES)
def test_every_mode_permits_white_because_it_is_the_eraser(mode):
    assert color_allowed(ERASER_COLOR, mode)
    assert color_allowed(ERASER_COLOR.upper(), mode)


def test_black_and_white_refuses_everything_else():
    assert color_allowed("#000000", "black_and_white")
    assert not color_allowed("#ed1c24", "black_and_white")


def test_palette_only_refuses_a_color_off_the_palette():
    assert color_allowed(PALETTE_COLORS[4], "palette")
    assert not color_allowed("#123456", "palette")


def test_all_colors_refuses_nothing():
    assert color_allowed("#123456", "all")


def test_colorblind_safe_is_its_own_palette_not_a_subset():
    """A subset of the built-in palette would not be safe: those pairs were
    chosen to look good and sit red next to green."""
    assert not set(COLORBLIND_SAFE_COLORS) <= set(PALETTE_COLORS)
    assert color_allowed(COLORBLIND_SAFE_COLORS[1], "colorblind_safe")
    assert not color_allowed("#ed1c24", "colorblind_safe")


def test_an_unknown_color_mode_is_refused():
    with pytest.raises(ValueError):
        check_color_mode("greyscale")


def test_a_packet_needs_both_its_tool_and_its_color():
    payload = {"color": "#ed1c24"}
    assert packet_allowed("draw_shape", payload, ["shapes"], "all")
    assert not packet_allowed("draw_shape", payload, ["brush"], "all")
    assert not packet_allowed("draw_shape", payload, ["shapes"], "black_and_white")
    # A frame carrying no color is judged on its tool alone
    assert packet_allowed("draw_move", {}, ["brush"], "black_and_white")


@pytest.mark.parametrize(
    "name,server",
    [
        ("PALETTE_COLORS", PALETTE_COLORS),
        ("COLORBLIND_SAFE_COLORS", COLORBLIND_SAFE_COLORS),
        ("BLACK_AND_WHITE_COLORS", BLACK_AND_WHITE_COLORS),
    ],
)
def test_the_client_offers_exactly_the_colors_the_server_admits(name, server):
    """A swatch the server refuses is a stroke that vanishes as the drawer
    makes it, and a color missing from the client is one nobody can reach.
    Neither shows up in either tree's own tests."""
    source = FRONTEND_RULES.read_text(encoding="utf-8")
    # The client builds its palette from the light/dark pairs the toolbar lays out.
    start = "export const COLOR_PAIRS" if name == "PALETTE_COLORS" else f"export const {name}"
    assert _hexes(source, start) == [color.lower() for color in server]
