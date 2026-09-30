import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  ClientCanvasHistory,
  calculateCanvasHistoryHash,
  decodeCanvasHistory,
} from "../src/lib/canvasHistory.ts";
import { decodeLiveDrawing, encodeFill } from "../src/lib/liveDrawing.ts";
import { createProtocolRenderer } from "../src/lib/protocolRenderer.ts";

// The accepted 100-fill turn (#1282): the costliest history a turn may hold.
const fillFixture = JSON.parse(readFileSync(new URL("../../fixtures/fill_replay_100.json", import.meta.url), "utf8"));
const fills = () => decodeCanvasHistory(Uint8Array.from(Buffer.from(fillFixture.base64, "base64")).buffer);
const protocol = JSON.parse(readFileSync(new URL("../../fixtures/canvas_protocol_v1.json", import.meta.url), "utf8"));
const strokes = () => decodeCanvasHistory(Uint8Array.from(
  protocol.histories.find((history) => history.name === "width-runs").binary.match(/../g),
  (byte) => Number.parseInt(byte, 16),
).buffer);

function surface() {
  const commits = [];
  return {
    pixels: new Uint8ClampedArray(CANVAS_WIDTH * CANVAS_HEIGHT * 4),
    commit(x, y, width, height) {
      commits.push([x, y, width, height]);
    },
    commits,
  };
}

const digest = (pixels) => createHash("sha256").update(pixels).digest("hex");

/** What an immediate replay of `actions` paints. */
function immediately(actions) {
  const target = surface();
  createProtocolRenderer({ current: target }, () => 80, null).replay(actions);
  return digest(target.pixels);
}

/** A viewer's renderer whose pieces run when the test says, on a clock that
advances 5 ms at every reading, so a 16 ms piece is a few actions. */
function viewer({ live = () => true } = {}) {
  const target = surface();
  const tasks = [];
  let clock = 0;
  const renderer = createProtocolRenderer({ current: target }, () => 80, null, undefined, {
    live,
    nextTask: (task) => tasks.push(task),
    now: () => (clock += 5),
  });
  const drain = () => {
    let ran = 0;
    while (tasks.length) {
      tasks.shift()();
      ran += 1;
    }
    return ran;
  };
  return { target, renderer, tasks, drain };
}

test("a viewer's replay plays out in pieces and ends on the pixels an immediate one paints (#1347)", () => {
  const actions = fills();
  const { target, renderer, tasks, drain } = viewer();

  renderer.replay(actions);
  assert.ok(tasks.length > 0, "the hundred fills did not all happen in the one task");
  assert.ok(target.commits.length >= 1, "the first piece is shown at once");
  const pieces = drain();

  assert.ok(pieces > 5, `played out over ${pieces} later tasks`);
  assert.equal(digest(target.pixels), immediately(actions));
  assert.ok(target.commits.length > pieces, "every piece is shown as it lands");
});

test("a short history is on the canvas before replay returns, as it always was", () => {
  const actions = strokes();
  const target = surface();
  const tasks = [];
  const renderer = createProtocolRenderer({ current: target }, () => 80, null, undefined, {
    live: () => true,
    nextTask: (task) => tasks.push(task),
    now: () => 0,
  });
  renderer.replay(actions);
  assert.equal(tasks.length, 0);
  assert.equal(digest(target.pixels), immediately(actions));
});

test("the drawer's replay is immediate: its own pointer paints the same pixels", () => {
  const actions = fills();
  const { target, renderer, tasks } = viewer({ live: () => false });
  renderer.replay(actions);
  assert.equal(tasks.length, 0);
  assert.equal(digest(target.pixels), immediately(actions));
});

test("frames that land mid-replay are painted in their place, from the history, and nowhere else", () => {
  // The protocol applies a frame to its history before `apply`: here, the
  // history grows and `apply` is handed the frame, as in a room.
  const history = fills();
  const extra = strokes();
  const { target, renderer, drain } = viewer();
  const scheduled = [];
  globalThis.window = {
    requestAnimationFrame: (callback) => scheduled.push(callback),
    cancelAnimationFrame() {},
  };
  try {
    renderer.replay(history);
    const shown = target.commits.length;
    for (const action of extra) {
      history.push(action);
      renderer.apply({ event: "draw_fill", payload: { x: 0.5, y: 0.5, color: "#123456" } });
    }
    // Painted early, a frame lands under whatever the replay has yet to
    // reach: a later fill covers it, so the final pixels alone cannot tell.
    assert.equal(target.commits.length, shown, "apply painted nothing mid-replay");
    assert.equal(scheduled.length, 0, "and queued nothing to paint later");
    drain();
  } finally {
    delete globalThis.window;
  }
  assert.equal(digest(target.pixels), immediately(history));
});

test("an open path that grows mid-replay is painted with every point it ends with", () => {
  const history = fills();
  const path = strokes().find((action) => action.kind === "path");
  const growing = { ...path, points: path.points.slice(0, 2) };
  history.push(growing);
  const { target, renderer, drain } = viewer();
  renderer.replay(history);
  growing.points.push(...path.points.slice(2));
  drain();
  assert.equal(digest(target.pixels), immediately(history));
});

test("an undo mid-replay starts over from the new history; the old one paints nothing more", () => {
  const history = fills();
  const { target, renderer, tasks, drain } = viewer();
  renderer.replay(history);
  const stale = tasks.length;
  const undone = history.slice(0, 60);
  renderer.replay(undone);
  drain();
  assert.ok(stale > 0);
  assert.equal(digest(target.pixels), immediately(undone));
});

test("a clear mid-replay leaves a white canvas, not the rest of the replay", () => {
  const { target, renderer, drain } = viewer();
  renderer.replay(fills());
  renderer.clear();
  drain();
  assert.ok(target.pixels.every((value) => value === 255));
});

test("a viewer who becomes the drawer mid-replay gets the rest at once", () => {
  let viewing = true;
  const actions = fills();
  const { target, renderer, tasks } = viewer({ live: () => viewing });
  renderer.replay(actions);
  viewing = false;
  tasks.shift()();
  assert.equal(tasks.length, 0, "finished in that task, before the drawer's pointer can paint");
  assert.equal(digest(target.pixels), immediately(actions));
});

test("a drawing started after a synced Clear is painted, though it begins a new history (#1368 review)", () => {
  // Starting an action after a Clear discards the pre-clear history in a
  // new array, which a replay reading the old one would never see.
  const history = new ClientCanvasHistory();
  const synced = [...fills(), { kind: "clear" }];
  assert.ok(history.replace(synced, 1, 1, synced.length, calculateCanvasHistoryHash(synced)));
  const { target, renderer, tasks, drain } = viewer();
  renderer.replay(history.actions);
  assert.ok(tasks.length > 0, "still playing out when the next frame lands");

  const packet = decodeLiveDrawing(encodeFill({ x: 0.25, y: 0.25, color: "#123456" }));
  assert.ok(history.apply(packet));
  assert.notEqual(history.actions, synced, "the history moved to a new array");
  renderer.apply(packet);
  drain();

  assert.equal(digest(target.pixels), immediately(history.actions));
});
