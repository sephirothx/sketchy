"""A room's drawing rules: which tools and which colors a drawer may use.

Two settings, deliberately shaped differently. Tools are independent flags, so
they are a set; colors are mutually exclusive alternatives - nothing is both
black-and-white and colorblind-safe - so they are one named mode.

The eraser is not in here, and cannot be. Erasing is a white brush stroke on
the wire (see ``useCanvasPointerInput.ts``), indistinguishable from drawing in
white, so the server can ban the brush and the eraser together or admit both,
but never one alone. That is also why every color mode permits white: taking it
away would take the eraser with it. Hence *black and white* rather than *black
only* - the two would behave identically, and the honest name is the one that
says so.
"""
from __future__ import annotations

BRUSH = "brush"
FILL = "fill"
SHAPES = "shapes"

DRAWING_TOOLS: tuple[str, ...] = (BRUSH, FILL, SHAPES)
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = DRAWING_TOOLS

# One of these has to stay selected. Fill on its own cannot draw anything; it
# can only flood an empty canvas, which is a room with no drawing in it.
TOOLS_REQUIRING_ONE: tuple[str, ...] = (BRUSH, SHAPES)

# Which chip governs each live-drawing event. All three path events answer to
# the brush, so turning the brush off turns the eraser off with it.
TOOL_BY_EVENT: dict[str, str] = {
    "draw_start": BRUSH,
    "draw_move": BRUSH,
    "draw_end": BRUSH,
    "draw_shape": SHAPES,
    "draw_fill": FILL,
}

# The built-in palette, in the order the toolbar lays it out: thirteen
# light/dark pairs flattened. Mirrors COLOR_PAIRS in `Toolbar.tsx`, and
# `test_drawing_rules.py` fails if the two drift apart.
PALETTE_COLORS: tuple[str, ...] = (
    "#ffffff", "#000000",
    "#c1c1c1", "#4c4c4c",
    "#ed1c24", "#7f0000",
    "#ff7f27", "#a0522d",
    "#fff200", "#c9a227",
    "#b5e61d", "#2d5b1e",
    "#22b14c", "#1c6b5a",
    "#7ac9e8", "#2e5090",
    "#3f48cc", "#1b1b6e",
    "#a349a4", "#5c2d91",
    "#ec6ea8", "#7b3f61",
    "#ffae85", "#a9714b",
    "#c69c6d", "#5b3a1e",
)

# The Okabe-Ito set, which stays distinguishable under protanopia,
# deuteranopia and tritanopia, plus white for the eraser. Not a subset of the
# palette above: those thirteen pairs were chosen to look good and put red and
# green families side by side, so no subset of them is genuinely safe.
COLORBLIND_SAFE_COLORS: tuple[str, ...] = (
    "#000000",  # black
    "#e69f00",  # orange
    "#56b4e9",  # sky blue
    "#009e73",  # bluish green
    "#f0e442",  # yellow
    "#0072b2",  # blue
    "#d55e00",  # vermillion
    "#cc79a7",  # reddish purple
    "#ffffff",  # white
)

BLACK_AND_WHITE_COLORS: tuple[str, ...] = ("#000000", "#ffffff")

# The color the client sends for an eraser stroke. Allowed everywhere.
ERASER_COLOR = "#ffffff"

COLOR_MODES: tuple[str, ...] = ("all", "palette", "colorblind_safe", "black_and_white")
DEFAULT_COLOR_MODE = "all"

_COLORS_BY_MODE: dict[str, tuple[str, ...]] = {
    "palette": PALETTE_COLORS,
    "colorblind_safe": COLORBLIND_SAFE_COLORS,
    "black_and_white": BLACK_AND_WHITE_COLORS,
}


def clean_allowed_tools(tools) -> list[str]:
    """Normalize a requested tool set: known tools only, canonical order, no
    duplicates. Raises when nothing is left to draw with."""
    if isinstance(tools, str) or not isinstance(tools, (list, tuple, set, frozenset)):
        raise ValueError("allowed tools must be a list")
    requested = set()
    for tool in tools:
        if not isinstance(tool, str) or tool not in DRAWING_TOOLS:
            raise ValueError(f"must be any of {', '.join(DRAWING_TOOLS)}")
        requested.add(tool)
    if not requested & set(TOOLS_REQUIRING_ONE):
        raise ValueError(
            f"at least one of {' and '.join(TOOLS_REQUIRING_ONE)} must be allowed"
        )
    return [tool for tool in DRAWING_TOOLS if tool in requested]


def check_color_mode(value: str) -> str:
    if value not in COLOR_MODES:
        raise ValueError(f"must be one of {', '.join(sorted(COLOR_MODES))}")
    return value


def allowed_colors(color_mode: str) -> tuple[str, ...] | None:
    """The colors a mode permits, or None when it permits every color."""
    return _COLORS_BY_MODE.get(color_mode)


def tool_allowed(event: str, allowed_tools) -> bool:
    """Whether the room's tool set admits this live-drawing event.

    Events with no tool behind them - clearing the canvas - are never a tool
    the host chose to take away.
    """
    tool = TOOL_BY_EVENT.get(event)
    return tool is None or tool in allowed_tools


def color_allowed(color: str | None, color_mode: str) -> bool:
    """Whether the mode admits this color. White always passes: it is the eraser."""
    if color is None:
        return True
    permitted = allowed_colors(color_mode)
    if permitted is None:
        return True
    normalized = color.lower()
    return normalized == ERASER_COLOR or normalized in permitted


def packet_allowed(event: str, payload: dict, allowed_tools, color_mode: str) -> bool:
    """The whole check for one decoded live-drawing packet."""
    return tool_allowed(event, allowed_tools) and color_allowed(
        payload.get("color"), color_mode
    )
