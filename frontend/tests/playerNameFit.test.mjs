/** A long name in the player list shrinks to fit its cell's content box.

The cell pads its text by the ink allowance (#1170), so a name fitted to the
whole cell overflowed the content box by that padding and ended in an
ellipsis; so did one fitted to `clientWidth`, which rounds. These pin the
arithmetic `fitPlayerNames` hands the measurements to. */
import assert from "node:assert/strict";
import test from "node:test";

import { fittedNameFontSize } from "../src/lib/playerName.ts";

// Measured in the waiting room at 1280px: a 160.6px cell padded 0.22em of
// its 15px, and "jWWWWWWWWWWWWWWf" in a guest's italic at 15px.
const CELL = { width: 160.59375, borderLeft: 0, borderRight: 0, paddingLeft: 3.3, paddingRight: 3.3 };
const LONG_NAME_AT_15PX = 241.11;

const contentWidth = (cell) =>
  cell.width - cell.borderLeft - cell.borderRight - cell.paddingLeft - cell.paddingRight;
const widthAt = (size, natural, current) => (natural * size) / current;

test("a name that fits keeps its size", () => {
  assert.equal(fittedNameFontSize(CELL, 40, 15), null);
  assert.equal(fittedNameFontSize(CELL, contentWidth(CELL), 15), null);
});

test("a long name fits the content box, not the padding", () => {
  const size = fittedNameFontSize(CELL, LONG_NAME_AT_15PX, 15);
  assert.ok(size !== null && size < 15, `shrinks: ${size}`);
  const width = widthAt(size, LONG_NAME_AT_15PX, 15);
  assert.ok(width <= contentWidth(CELL), `${width} fits in ${contentWidth(CELL)}`);
  // Fitted to the padding box it would have run into the padding.
  assert.ok(width < CELL.width - 6, `${width} clears the padding`);
  // And it is not shrunk further than the rounding asks.
  assert.ok(contentWidth(CELL) - width < widthAt(0.1, LONG_NAME_AT_15PX, 15));
});

test("a fraction of a pixel short of a whole one still fits", () => {
  // clientWidth reports 160.4 as 160 and 160.6 as 161; the fit must use the
  // real width, and land inside it.
  for (const width of [160.4, 160.6, 99.99]) {
    const cell = { width, borderLeft: 0, borderRight: 0, paddingLeft: 0, paddingRight: 0 };
    const size = fittedNameFontSize(cell, 300, 15);
    assert.ok(widthAt(size, 300, 15) <= width, `${width}: ${size}px`);
  }
});

test("borders come off the width too", () => {
  const cell = { ...CELL, borderLeft: 1.5, borderRight: 1.5 };
  const size = fittedNameFontSize(cell, LONG_NAME_AT_15PX, 15);
  assert.ok(widthAt(size, LONG_NAME_AT_15PX, 15) <= contentWidth(cell));
});

test("a cell with no room yet is left alone", () => {
  const hidden = { width: 0, borderLeft: 0, borderRight: 0, paddingLeft: 0, paddingRight: 0 };
  assert.equal(fittedNameFontSize(hidden, 120, 15), null);
  assert.equal(fittedNameFontSize({ ...hidden, width: 6, paddingLeft: 3.3, paddingRight: 3.3 }, 120, 15), null);
});

test("the fitted text never overflows, whatever the sizes", () => {
  for (let width = 40; width <= 400; width += 7.37) {
    for (const padding of [0, 2.53, 3.3, 4.4]) {
      for (const natural of [50, 180.5, 241.11, 612.9]) {
        for (const current of [11.5, 14, 15, 22]) {
          const cell = { width, borderLeft: 0, borderRight: 0, paddingLeft: padding, paddingRight: padding };
          const size = fittedNameFontSize(cell, natural, current);
          const fitted = size === null ? natural : widthAt(size, natural, current);
          assert.ok(fitted <= contentWidth(cell) + 1e-9, `${width}/${padding}/${natural}/${current}`);
        }
      }
    }
  }
});
