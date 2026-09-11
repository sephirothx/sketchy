import assert from "node:assert/strict";
import test from "node:test";

import {
  ARRANGEMENTS,
  arrangementOf,
  arrangementWidth,
  chooseToolbarLayout,
} from "../src/lib/toolbarLayout.ts";

// Widths of the real toolbar, rounded: six tools, the size readout at 6px,
// the paired palette with its custom swatch, and a divider with its gaps.
const SHARED = { tools: 279, size: 66, palette: 390, separator: 27.5, chrome: 31 };
const ENGLISH = { ...SHARED, actions: 175, actionIcons: 97 };
// "Ongedaan maken" and "Leegmaken": the longest pair in the seven catalogues.
const DUTCH = { ...SHARED, actions: 274, actionIcons: 97 };

// The room's middle column at its widest, a 1240px window and up.
const WIDEST_COLUMN = 632;

test("every arrangement shows each group once, tools and size first", () => {
  for (const { layout, rows } of ARRANGEMENTS) {
    assert.deepEqual(
      rows.flat().toSorted(),
      ["actions", "palette", "size", "tools"],
      `${layout} should hold every group exactly once`,
    );
    // The hook reads the spacing off the divider between these two, so it
    // has to be on screen whichever arrangement is.
    assert.deepEqual(rows[0].slice(0, 2), ["tools", "size"], `${layout} should open with tools, size`);
  }
});

test("the single line needs every group and a divider between each", () => {
  const row = arrangementOf("row");
  assert.equal(arrangementWidth(row, ENGLISH), 31 + 279 + 66 + 390 + 175 + 3 * 27.5);
  // Which is why no desktop room has ever shown it.
  assert.notEqual(chooseToolbarLayout(ENGLISH, WIDEST_COLUMN), "row");
  assert.equal(chooseToolbarLayout(ENGLISH, 1100), "row");
});

test("at the widest column, English keeps its labels beside the tools", () => {
  assert.equal(chooseToolbarLayout(ENGLISH, WIDEST_COLUMN), "split");
});

test("a longer language drops to icons rather than to a third line", () => {
  assert.equal(chooseToolbarLayout(DUTCH, WIDEST_COLUMN), "split-icons");
  assert.equal(chooseToolbarLayout(ENGLISH, 540), "split-icons");
});

test("each group gets its own line once not even the icons fit beside the tools", () => {
  assert.equal(chooseToolbarLayout(ENGLISH, 500), "stack");
  assert.equal(chooseToolbarLayout(DUTCH, 500), "stack");
});

test("a column narrower than the palette gets the chip strip", () => {
  assert.equal(chooseToolbarLayout(ENGLISH, 420), "compact");
  // 901px window: 901 - 32 room padding - 252 - 292 sidebars - 32 gaps.
  assert.equal(chooseToolbarLayout(DUTCH, 293), "compact");
});

test("a room that allows less keeps a fuller toolbar in the same column", () => {
  // Brush alone, and black and white: two swatches and the custom one.
  const sparse = { ...ENGLISH, tools: 44, palette: 82 };
  assert.equal(chooseToolbarLayout(sparse, 420), "split");
});

test("a toolbar that fits only to the pixel gets the next arrangement", () => {
  const split = arrangementWidth(arrangementOf("split"), ENGLISH);
  assert.equal(chooseToolbarLayout(ENGLISH, split + 0.5), "split");
  assert.equal(chooseToolbarLayout(ENGLISH, split), "split-icons");
});
