/** Repainting a history from a recent snapshot of it, not from white (#989).

An undo repaints the drawing from its history, on every client, and it used
to start from a white canvas every time: 20-100 ms for a history of wide
strokes or fills on a laptop, several times that on a phone, and a fill-heavy
turn could reach hundreds. The history is a stack - actions are appended,
popped by undo, or replaced wholesale by a sync - so a copy of the pixels
after its first N actions stays true for as long as those N are still its
first N, and an undo replays only what came after the newest such copy.

Kept small on purpose: two copies of 1.9 MB, taken every eight actions once a
history is long enough for a replay to cost something, and recycled rather
than reallocated. An undo takes back the last action or two, so the newest
copy is nearly always the one used.

**What makes a copy stale.** It records the object of its last action, and
the history's action at that index must still be that object - a pop below
it, or a sync that decoded fresh objects, fails that. And the history grows
its open path in place, so a copy never includes the action that is last when
it is taken, is never used when its own last action is last again (a path
there could reopen), and a path's point count is checked too: a copy whose
last path has grown since is dropped.

The result is the pixels a replay from white would produce, byte for byte:
the same `applyCanvasAction` over the same actions, from a copy of exactly
what it had produced before. `tests/replayCheckpoints.test.mjs` holds it to
that across pushes, pops, syncs and growing paths. */
import type { DecodedCanvasAction } from "./canvasHistory.ts";
import { fillWhitePixels } from "./canvasPixels.ts";
import { applyCanvasAction } from "./canvasRenderer.ts";

export const CHECKPOINT_EVERY = 8;
export const MAX_CHECKPOINTS = 2;
/** Below this many actions a replay from white costs too little to be worth
    3.8 MB of copies. */
export const MIN_CHECKPOINT_LENGTH = 16;

interface Checkpoint {
  /** How many actions the copy includes. */
  length: number;
  last: DecodedCanvasAction;
  /** The last action's point count when copied, when it is a path. */
  lastPoints: number;
  pixels: Uint8ClampedArray;
}

function pointCount(action: DecodedCanvasAction): number {
  return action.kind === "path" ? action.points.length : -1;
}

export interface ReplayCheckpoints {
  /** Paint `actions` into `pixels` as a replay from white would, starting
      from the newest copy still true of them. Returns how many actions it
      applied. */
  replayInto(pixels: Uint8ClampedArray, actions: readonly DecodedCanvasAction[]): number;
  /** The first half of `replayInto`, for a replay that pauses between
      actions (#1347): put the newest copy still true of `actions` into
      `pixels`, or white, and return the index to apply from. */
  begin(pixels: Uint8ClampedArray, actions: readonly DecodedCanvasAction[]): number;
  /** Apply `actions[index]` onto `pixels`, which hold its first `index`
      actions, and keep a copy where `replayInto` would. The history may have
      grown since `begin`; what may be copied is judged against it as it is. */
  step(pixels: Uint8ClampedArray, actions: readonly DecodedCanvasAction[], index: number): void;
  /** Forget every copy - a new canvas, or a renderer going away. */
  clear(): void;
}

export function createReplayCheckpoints(): ReplayCheckpoints {
  // Ascending by length.
  let kept: Checkpoint[] = [];

  const stillTrue = (checkpoint: Checkpoint, actions: readonly DecodedCanvasAction[]) =>
    checkpoint.length < actions.length
    && actions[checkpoint.length - 1] === checkpoint.last
    && pointCount(checkpoint.last) === checkpoint.lastPoints;

  const begin = (pixels: Uint8ClampedArray, actions: readonly DecodedCanvasAction[]): number => {
    kept = kept.filter((checkpoint) => stillTrue(checkpoint, actions));
    const from = kept.at(-1);
    if (from) {
      pixels.set(from.pixels);
      return from.length;
    }
    fillWhitePixels(pixels);
    return 0;
  };

  const step = (
    pixels: Uint8ClampedArray,
    actions: readonly DecodedCanvasAction[],
    index: number,
  ): void => {
    applyCanvasAction(pixels, actions[index] as DecodedCanvasAction);
    const length = index + 1;
    // The last action may still grow (an open path), so no copy includes it.
    if (
      length <= actions.length - 1
      && length >= MIN_CHECKPOINT_LENGTH
      && length % CHECKPOINT_EVERY === 0
      && (kept.at(-1)?.length ?? 0) < length
    ) {
      const buffer = kept.length >= MAX_CHECKPOINTS
        ? kept.shift()!.pixels
        : new Uint8ClampedArray(pixels.length);
      buffer.set(pixels);
      const last = actions[index] as DecodedCanvasAction;
      kept.push({ length, last, lastPoints: pointCount(last), pixels: buffer });
    }
  };

  return {
    replayInto(pixels, actions) {
      const start = begin(pixels, actions);
      for (let index = start; index < actions.length; index++) step(pixels, actions, index);
      return actions.length - start;
    },
    begin,
    step,
    clear() {
      kept = [];
    },
  };
}
