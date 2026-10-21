import assert from "node:assert/strict";
import test from "node:test";

import {
  AXIS_LOCK_PX,
  OVERVIEW_THRESHOLD,
  RUBBER_BAND,
  ZOOM_SCALE,
  arrowKeyMoves,
  clampPan,
  closesOnRelease,
  dragAxis,
  dragOffset,
  lastStripStart,
  offersOverview,
  slideDurationMs,
  stripStartAfterMove,
  stripStartFor,
  swipeOutcome,
  zoomOriginOffset,
} from "../src/lib/drawingViewer.ts";

const swipe = (dx, ms, index = 3, total = 10) => swipeOutcome({ dx, ms, width: 360, index, total });

test("a drag is a tap until it moves past the axis lock", () => {
  assert.equal(dragAxis(AXIS_LOCK_PX, 0), null);
  assert.equal(dragAxis(AXIS_LOCK_PX + 1, 0), "x");
  assert.equal(dragAxis(3, -(AXIS_LOCK_PX + 1)), "y");
  // A diagonal goes to whichever way it moved more.
  assert.equal(dragAxis(12, 9), "x");
  assert.equal(dragAxis(9, 12), "y");
});

test("a slow drag changes drawing past half the width, and not before", () => {
  assert.equal(swipe(-170, 1000), "stay");
  assert.equal(swipe(-190, 1000), "next");
  assert.equal(swipe(190, 1000), "previous");
});

test("a flick changes drawing however short it is", () => {
  assert.equal(swipe(-40, 60), "next");
  assert.equal(swipe(40, 60), "previous");
  assert.equal(swipe(-40, 200), "stay");
});

test("there is nothing to swipe to past either end", () => {
  assert.equal(swipe(300, 100, 0), "stay");
  assert.equal(swipe(-300, 100, 9), "stay");
  assert.equal(dragOffset(90, 0, 10), 90 * RUBBER_BAND);
  assert.equal(dragOffset(-90, 9, 10), -90 * RUBBER_BAND);
  assert.equal(dragOffset(90, 4, 10), 90);
});

test("a downward drag closes past its distance or on a flick, an upward one never", () => {
  assert.equal(closesOnRelease(100, 1000), false);
  assert.equal(closesOnRelease(130, 1000), true);
  assert.equal(closesOnRelease(60, 50), true);
  assert.equal(closesOnRelease(-200, 50), false);
});

test("the slide is quicker the less of it is left", () => {
  assert.equal(slideDurationMs(0, 360), 300);
  assert.equal(slideDurationMs(-360, 360), 140);
  assert.ok(slideDurationMs(-200, 360) < slideDurationMs(-50, 360));
  // No width measured yet: the whole slide.
  assert.equal(slideDurationMs(100, 0), 300);
});

test("the strip pages by its size and only follows the drawing off its page", () => {
  assert.equal(stripStartFor(0, 8), 0);
  assert.equal(stripStartFor(7, 8), 0);
  assert.equal(stripStartFor(8, 8), 8);
  assert.equal(lastStripStart(60, 8), 56);
  assert.equal(lastStripStart(8, 8), 0);
  assert.equal(lastStripStart(0, 8), 0);
  // Paged ahead by hand, a drawing still on the page leaves it there.
  assert.equal(stripStartAfterMove(16, 20, 8), 16);
  // A drawing off the page brings the strip to the page that holds it.
  assert.equal(stripStartAfterMove(16, 15, 8), 8);
  assert.equal(stripStartAfterMove(0, 33, 8), 32);
});

test("the overview is offered only above a default game", () => {
  assert.equal(OVERVIEW_THRESHOLD, 24);
  assert.equal(offersOverview(24), false);
  assert.equal(offersOverview(25), true);
  assert.equal(offersOverview(6), false);
});

test("a double tap zooms on the point tapped, and a pan never shows past the drawing", () => {
  // The centre stays where it is.
  assert.deepEqual(zoomOriginOffset(0.5, 0.5, 400, 300), { x: 0, y: 0 });
  // A tap at the left edge moves the drawing right by half its width.
  assert.deepEqual(zoomOriginOffset(0, 0.5, 400, 300), { x: 200 * (ZOOM_SCALE - 1), y: 0 });
  assert.deepEqual(clampPan(999, -999, 400, 300), { x: 200, y: -150 });
  assert.deepEqual(clampPan(20, 10, 400, 300), { x: 20, y: 10 });
});

test("the arrow keys move the viewer, but not while somebody is typing", () => {
  const press = (key, target = { tagName: "BODY" }, extra = {}) =>
    arrowKeyMoves({ key, defaultPrevented: false, altKey: false, ctrlKey: false, metaKey: false, target, ...extra });
  assert.equal(press("ArrowLeft"), "previous");
  assert.equal(press("ArrowRight"), "next");
  assert.equal(press("ArrowUp"), null);
  assert.equal(press("ArrowRight", { tagName: "INPUT" }), null);
  assert.equal(press("ArrowRight", { tagName: "TEXTAREA" }), null);
  assert.equal(press("ArrowRight", { tagName: "DIV", isContentEditable: true }), null);
  assert.equal(press("ArrowRight", { tagName: "BODY" }, { defaultPrevented: true }), null);
  assert.equal(press("ArrowRight", { tagName: "BODY" }, { altKey: true }), null);
});
