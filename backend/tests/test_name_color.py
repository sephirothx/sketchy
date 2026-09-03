"""The name-colour rule (#571): readable on both player-list panels, wherever written."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.rooms import (
    NAME_COLOR_MIN_CONTRAST,
    NAME_COLOR_SURFACES,
    NAME_COLORS,
    contrast_ratio,
    name_color_is_readable,
    normalize_name_color,
)

REPO = Path(__file__).resolve().parent.parent.parent
THEME_CSS = REPO / "frontend" / "src" / "styles" / "theme.css"
SETTINGS_STORE = REPO / "frontend" / "src" / "store" / "settingsStore.ts"


def test_the_contrast_ratio_is_wcag():
    # The two anchors of the scale, and a pair a calculator agrees on.
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)
    # Symmetric: which one is the text does not matter.
    assert contrast_ratio("#1e293b", "#ef3c63") == contrast_ratio("#ef3c63", "#1e293b")


def test_every_palette_colour_clears_the_floor_on_both_panels():
    """The palette and the rule are one decision: the swatches the client
    offers must all be accepted by the server, on the light panel and the dark."""
    for color in NAME_COLORS:
        for surface in NAME_COLOR_SURFACES:
            assert contrast_ratio(color, surface) >= NAME_COLOR_MIN_CONTRAST, (
                f"{color} is only {contrast_ratio(color, surface):.2f}:1 on {surface}"
            )
        assert normalize_name_color(color) == color


@pytest.mark.parametrize(
    "color",
    [
        "#ffffff",  # invisible on the light panel
        "#faf6ef",  # the light page itself
        "#000000",  # invisible on the dark panel
        "#1e293b",  # the dark panel itself
        "#112233",  # near-black: fine on white, 1.1:1 on slate
        "#aabbcc",  # pale: 7.5:1 on slate, 2:1 on white
        "#00ff00",  # pure green reads on slate, not on white
    ],
)
def test_a_well_formed_but_unreadable_colour_is_treated_as_unset(color):
    assert not name_color_is_readable(color)
    assert normalize_name_color(color) is None
    assert normalize_name_color(color.upper()) is None


@pytest.mark.parametrize("value", ["red", "#fff", "#12345", "#gggggg", 12, None, ""])
def test_a_malformed_colour_is_still_refused(value):
    assert normalize_name_color(value) is None


def test_a_readable_colour_outside_the_palette_is_still_accepted():
    # The server holds the rule, not the list: the swatches are a courtesy,
    # and a future client offering another readable colour is not refused.
    assert normalize_name_color("#FF0000") == "#ff0000"


def _css_token(theme_block: str, token: str) -> str:
    match = re.search(rf"--{token}:\s*(#[0-9a-fA-F]{{6}})\s*;", theme_block)
    assert match, f"--{token} is not a hex value in that block"
    return match.group(1).lower()


def test_the_surfaces_are_the_player_list_panel_in_each_theme():
    """The server mirrors two hex values from theme.css. If the panel colour
    moves there, this is what says the rule is now checking the wrong thing."""
    css = THEME_CSS.read_text(encoding="utf-8")
    light, dark = css.split('[data-theme="dark"]', 1)
    # The player list sits in a `.panel`, whose ground is --card.
    assert set(NAME_COLOR_SURFACES) == {_css_token(light, "card"), _css_token(dark, "card")}


def test_the_client_palette_is_the_server_palette():
    source = SETTINGS_STORE.read_text(encoding="utf-8")
    block = source.split("NAME_COLOR_PALETTE = [", 1)[1].split("]", 1)[0]
    client = tuple(re.findall(r'"(#[0-9a-f]{6})"', block))
    assert client == NAME_COLORS
