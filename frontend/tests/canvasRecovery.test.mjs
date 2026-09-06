import assert from "node:assert/strict";
import test from "node:test";

import { ClientCanvasHistory } from "../src/lib/canvasHistory.ts";
import {
  COMPLETION_RETRIES_MS,
  CompletionWatch,
  MAX_REPLAY_POINTS,
  REPLAY_BURST,
  RecoverySender,
  observeServerCanvasSequence,
  onServerCanvasSequence,
  pointCount,
  repackDrawFrames,
  staleNoticeAction,
} from "../src/lib/canvasRecovery.ts";
import {
  decodeLiveDrawing,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
} from "../src/lib/liveDrawing.ts";

function stroke(points, batch = 1) {
  const frames = [encodePathStart({ x: 0.1, y: 0.1, color: "#000000", width: 6 })];
  for (let index = 0; index < points.length; index += batch) {
    frames.push(encodePathPoints({ points: points.slice(index, index + batch) }));
  }
  frames.push(encodePathEnd());
  return frames;
}

function replayInto(frames) {
  const history = new ClientCanvasHistory();
  history.replace([], 0, 1, 0, 0);
  for (const frame of frames) assert.ok(history.apply(decodeLiveDrawing(frame)));
  return history;
}

const points = Array.from({ length: 150 }, (_, i) => ({ x: 0.1 + i / 1000, y: 0.1 + (i % 7) / 500 }));

test("a six-second stroke of 152 frames repacks to three with the same history and hash", () => {
  const original = stroke(points);
  assert.equal(original.length, 152);
  const repacked = repackDrawFrames(original);
  assert.equal(repacked.length, 3);
  assert.equal(pointCount(repacked), 150);
  const before = replayInto(original);
  const after = replayInto(repacked);
  assert.deepEqual(after.actions, before.actions);
  assert.equal(after.historyHash, before.historyHash);
  assert.equal(after.revision, before.revision);
});

test("more than 256 points repacks into the fewest codec-valid frames", () => {
  const many = Array.from({ length: 750 }, (_, i) => ({ x: (i % 800) / 800, y: Math.floor(i / 800) / 600 + 0.1 }));
  const repacked = repackDrawFrames(stroke(many, 5));
  assert.equal(repacked.length, 5); // start + 256 + 256 + 238 + end
  assert.equal(replayInto(repacked).historyHash, replayInto(stroke(many, 5)).historyHash);
});

test("anything that is not a closed path is returned as it was", () => {
  const open = stroke(points).slice(0, -1);
  assert.equal(repackDrawFrames(open), open);
  const fill = [new Uint8Array([0x14, 0, 0, 0, 0, 0, 0, 0])];
  assert.equal(repackDrawFrames(fill), fill);
});

function fakeClock() {
  const state = { now: 0, timers: [] };
  return {
    state,
    now: () => state.now,
    schedule: (callback, delayMs) => {
      const handle = { at: state.now + delayMs, callback };
      state.timers.push(handle);
      return handle;
    },
    cancel: (handle) => {
      state.timers = state.timers.filter((timer) => timer !== handle);
    },
    advance(ms) {
      const until = state.now + ms;
      for (;;) {
        const due = state.timers.filter((timer) => timer.at <= until).sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        state.now = due.at;
        state.timers = state.timers.filter((timer) => timer !== due);
        due.callback();
      }
      state.now = until;
    },
  };
}

function sender(allowance = { drawingFramesPerWindow: 100, drawingWindowSeconds: 2 }) {
  const clock = fakeClock();
  const sent = [];
  const tooLarge = [];
  const instance = new RecoverySender({
    emit: (frame, identity) => sent.push({ at: clock.now(), frame, identity }),
    allowance: () => allowance,
    now: clock.now,
    schedule: clock.schedule,
    cancel: clock.cancel,
    tooLarge: () => tooLarge.push(true),
  });
  return { instance, sent, tooLarge, clock };
}

test("a replay is paced under the advertised allowance with a reserve, after a small burst", () => {
  const { instance, sent, clock } = sender();
  const frames = stroke(Array.from({ length: 5000 }, (_, i) => ({ x: (i % 800) / 800, y: 0.2 })), 5);
  instance.enqueue({ sequence: 1, frames, identity: [1, 1] });
  assert.equal(sent.length, 0, "nothing leaves inside enqueue");
  clock.advance(0);
  assert.equal(sent.length, REPLAY_BURST, "the burst goes out on the next tick");
  assert.deepEqual(sent[0].identity, [1, 1]);
  assert.equal(sent[1].identity, undefined);
  clock.advance(2000);
  // 100 per 2 s, 25% reserved: 75 frames per window, so 75 - burst more in the first 2 s.
  assert.ok(sent.length <= 75 + 1 && sent.length >= 70, `sent ${sent.length} in the first window`);
  clock.advance(60_000);
  assert.equal(sent.length, frames.length);
  assert.equal(instance.pending, 0);
});

test("repeated requests for the same sequence cost one replay; different sequences queue in order", () => {
  const { instance, sent, clock } = sender();
  const a = stroke(points.slice(0, 40), 5);
  const b = stroke(points.slice(40, 80), 5);
  instance.enqueue({ sequence: 2, frames: b, identity: [1, 2] });
  instance.enqueue({ sequence: 1, frames: a, identity: [1, 1] });
  instance.enqueue({ sequence: 2, frames: b, identity: [1, 2] });
  instance.enqueue({ sequence: 2, frames: b, identity: [1, 2] });
  clock.advance(10_000);
  assert.equal(sent.length, a.length + b.length, "sequence 2 was queued three times and sent once");
  assert.deepEqual(sent[0].identity, [1, 1]);
  assert.deepEqual(sent[a.length].identity, [1, 2]);
});

test("cancel stops a replay mid-way and nothing more is sent", () => {
  const { instance, sent, clock } = sender();
  instance.enqueue({ sequence: 1, frames: stroke(points), identity: [1, 1] });
  clock.advance(0);
  const before = sent.length;
  assert.ok(before > 0 && before < 152);
  instance.cancel();
  clock.advance(60_000);
  assert.equal(sent.length, before);
  assert.equal(instance.pending, 0);
});

test("a replay past the point bound is refused whole and reported", () => {
  const { instance, sent, tooLarge, clock } = sender();
  const huge = stroke(Array.from({ length: MAX_REPLAY_POINTS + 1 }, (_, i) => ({ x: (i % 800) / 800, y: 0.3 })), 5);
  instance.enqueue({ sequence: 1, frames: huge, identity: [1, 1] });
  clock.advance(60_000);
  assert.equal(tooLarge.length, 1);
  assert.equal(sent.length, 0);
});

test("a finished action is resent with backoff and then given up on", () => {
  const clock = fakeClock();
  const resent = [];
  const gaveUp = [];
  const watch = new CompletionWatch({
    schedule: clock.schedule,
    cancel: clock.cancel,
    resend: (sequence) => resent.push([clock.now(), sequence]),
    giveUp: (sequence) => gaveUp.push([clock.now(), sequence]),
  });
  watch.arm(7);
  clock.advance(COMPLETION_RETRIES_MS[0] - 1);
  assert.deepEqual(resent, []);
  clock.advance(1);
  assert.deepEqual(resent, [[2000, 7]]);
  clock.advance(COMPLETION_RETRIES_MS[1]);
  assert.deepEqual(resent, [[2000, 7], [6000, 7]]);
  assert.deepEqual(gaveUp, []);
  clock.advance(COMPLETION_RETRIES_MS[2]);
  assert.deepEqual(gaveUp, [[14000, 7]]);
  assert.equal(watch.isArmed(7), false);
  clock.advance(60_000);
  assert.equal(resent.length, 2, "nothing after giving up");
});

test("a confirmation disarms the watch; the server's sequence fires it early", () => {
  const clock = fakeClock();
  const resent = [];
  const watch = new CompletionWatch({
    schedule: clock.schedule,
    cancel: clock.cancel,
    resend: (sequence) => resent.push(sequence),
    giveUp: () => assert.fail("must not give up"),
  });
  watch.arm(3);
  watch.arm(4);
  watch.confirm(3);
  clock.advance(1_000);
  assert.ok(!watch.isArmed(3) && watch.isArmed(4));
  watch.confirm(4);
  watch.arm(5);
  watch.serverCommitted(5);
  assert.deepEqual(resent.slice(-1), [5], "committed on the server but unconfirmed here: resend now");
  watch.cancelAll();
  assert.ok(!watch.isArmed(4) && !watch.isArmed(5));
});

test("the heartbeat's canvas sequence reaches whoever listens, and junk does not", () => {
  const seen = [];
  const stop = onServerCanvasSequence((generation, sequence) => seen.push([generation, sequence]));
  observeServerCanvasSequence(2, 9);
  observeServerCanvasSequence("2", 9);
  observeServerCanvasSequence(2, 1.5);
  stop();
  observeServerCanvasSequence(2, 10);
  assert.deepEqual(seen, [[2, 9]]);
});

test("a stale notice discards pending work, except a deferral which only waits", () => {
  assert.deepEqual(staleNoticeAction([3, 7, "stale_generation", 2000], 2), { discardPending: true, delayMs: 0 });
  assert.deepEqual(staleNoticeAction([3, 0, "refused_tool", 2000], 3), { discardPending: true, delayMs: 0 });
  assert.deepEqual(staleNoticeAction([3, 0, "deferred", 2000], 3), { discardPending: false, delayMs: 2000 });
  assert.deepEqual(staleNoticeAction([3, 0, "deferred", 0], 3), { discardPending: false, delayMs: 0 });
  assert.equal(staleNoticeAction([3, 0], 3), null);
  assert.equal(staleNoticeAction("nope", 3), null);
  assert.equal(staleNoticeAction([3, 0, 5, 2000], 3), null);
});
