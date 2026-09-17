import assert from "node:assert/strict";
import test from "node:test";

import { ScratchSheet } from "../src/lib/scratchPad.ts";
import {
  encodeFill,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
  encodeShape,
} from "../src/lib/liveDrawing.ts";

function stroke(sheet, from, to) {
  assert.ok(sheet.apply(encodePathStart({ ...from, color: "#000000", width: 6 })));
  assert.ok(sheet.apply(encodePathPoints({ points: [to], previous: from })));
  assert.ok(sheet.apply(encodePathEnd()));
}

test("every tool the game has lands on the sheet as the game's own actions", () => {
  const sheet = new ScratchSheet();
  stroke(sheet, { x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 });
  assert.ok(sheet.apply(encodeShape({
    shape: "ellipse",
    from: { x: 0.2, y: 0.2 },
    to: { x: 0.4, y: 0.4 },
    color: "#ed1c24",
    width: 4,
  })));
  assert.ok(sheet.apply(encodeFill({ x: 0.9, y: 0.9, color: "#1234de" })));
  assert.deepEqual(sheet.actions.map((action) => action.kind), ["path", "shape", "fill"]);
  assert.equal(sheet.actions[0].points.length, 2);
});

test("undo takes back the last action, and a clear is an action it can take back", () => {
  const sheet = new ScratchSheet();
  stroke(sheet, { x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 });
  stroke(sheet, { x: 0.6, y: 0.1 }, { x: 0.9, y: 0.5 });
  assert.ok(sheet.undo());
  assert.equal(sheet.actions.length, 1);

  assert.ok(sheet.clear());
  assert.equal(sheet.actions.at(-1).kind, "clear");
  assert.equal(sheet.clear(), false, "a sheet that is already clear is not cleared again");
  assert.ok(sheet.undo());
  assert.deepEqual(sheet.actions.map((action) => action.kind), ["path"]);

  assert.ok(sheet.undo());
  assert.equal(sheet.undo(), false, "nothing left to take back");
});

test("points with no path open are refused rather than joined to the last stroke", () => {
  const sheet = new ScratchSheet();
  assert.equal(sheet.apply(encodePathEnd()), false);
  assert.deepEqual(sheet.actions, []);
});

test("a change is announced to every other pad on the sheet, not back to its own", () => {
  const sheet = new ScratchSheet();
  const seen = [];
  const drawnOn = () => seen.push("drawnOn");
  const other = (actions) => seen.push(`other:${actions.length}`);
  const unsubscribe = sheet.subscribe(drawnOn);
  sheet.subscribe(other);
  stroke(sheet, { x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 });
  sheet.changed(drawnOn);
  assert.deepEqual(seen, ["other:1"]);

  unsubscribe();
  sheet.changed(other);
  assert.deepEqual(seen, ["other:1"]);
});
