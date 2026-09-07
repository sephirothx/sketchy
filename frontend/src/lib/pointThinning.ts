/** Thinning a brush stroke's pointer samples as they arrive (#560).

A pointer reports up to 120 samples a second, and the client used to queue
every one: exact duplicates when the hand paused, and runs of samples along
what is, at a quarter-pixel quantization, one straight segment. Every sample
costs four bytes in the live frame and in the stored history, a share of the
turn's 25 000-point budget, and replay work on every screen that joins.

This keeps only the samples that change the drawn line by more than
`THINNING_TOLERANCE_PX`, with a bound that holds for the whole stroke, not
sample by sample: an **anchor** (the last sample kept) and one **pending**
sample; a new sample replaces the pending one only if every sample dropped
since the anchor lies within the tolerance of the segment from the anchor to
the new sample. When one does not, the pending sample is kept and becomes
the anchor. So the segment that finally replaces a run of dropped samples was
checked against all of them, and no sample is ever farther from the polyline
sent than the tolerance - repeatedly dropping local candidates cannot
accumulate error. A sharp corner fails the test and is kept; a reversal
along the same line fails it (the far point is far from the short segment
back) and its turning point is kept; the first sample is kept as the anchor
and the last is kept by `end()`; a dot is one sample. A corner is preserved
exactly when the pen turned enough to move the line by more than the
tolerance at some sample, and at 0.25 px that is what "turned" means.

The flush timer forces the pending sample out (`flush()`), which keeps the
error bound and lets viewers watch a long straight stroke advance every
flush rather than only when it bends or ends; measured, that costs about
ten points in a hundred against holding it (`benchmarks/point_thinning.py`).

**Rendering follows the same points.** The drawer's own canvas is painted
with the kept samples, exactly as the viewers paint them from the frames,
so local and remote rasters are one raster, and a flood fill sees the same
edges everywhere. The pending sample is shown to the drawer on the preview
layer, so the line under the pen does not lag a sample behind.

Coordinates here are normalized (0-1 over the canvas); the tolerance is in
canvas pixels, and the test converts. */

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "./canvasHistory.ts";
import type { StrokePoint } from "../types";

/** How far, in canvas pixels, a dropped sample may lie from the line sent.
One quantization step: a stroke's edge never moves by more than the
resolution the samples had, and measured on recorded hand strokes fill
topology was unchanged while half the points went (#560). */
export const THINNING_TOLERANCE_PX = 0.25;

export interface PointThinner {
  /** Offer a sample; returns the samples kept because of it, in order. */
  push(point: StrokePoint): StrokePoint[];
  /** Force the pending sample out, for a flush. Returns it if there was one. */
  flush(): StrokePoint[];
  /** The stroke ended: the last sample is kept. */
  end(): StrokePoint[];
  /** The sample under the pen that has not been kept yet, for the preview. */
  pending(): StrokePoint | null;
  /** The last kept sample, which the preview segment starts from. */
  anchor(): StrokePoint;
}

function distanceToSegmentPx(p: StrokePoint, a: StrokePoint, b: StrokePoint): number {
  const ax = a.x * CANVAS_WIDTH;
  const ay = a.y * CANVAS_HEIGHT;
  const bx = b.x * CANVAS_WIDTH;
  const by = b.y * CANVAS_HEIGHT;
  const px = p.x * CANVAS_WIDTH;
  const py = p.y * CANVAS_HEIGHT;
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  let t = 0;
  if (lengthSquared > 0) {
    t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSquared));
  }
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function same(a: StrokePoint, b: StrokePoint): boolean {
  return a.x === b.x && a.y === b.y;
}

/** A thinner for one stroke, anchored at its first sample. */
export function createPointThinner(
  start: StrokePoint,
  tolerancePx: number = THINNING_TOLERANCE_PX,
): PointThinner {
  let anchor = start;
  let pending: StrokePoint | null = null;
  let lastSeen = start;
  // Every sample dropped since the anchor. Bounded in practice by how long
  // the pen moves straight between flushes; the check over it is what makes
  // the bound a whole-stroke one.
  let dropped: StrokePoint[] = [];

  function keep(point: StrokePoint): StrokePoint {
    anchor = point;
    dropped = [];
    return point;
  }

  function fits(candidate: StrokePoint): boolean {
    if (pending && distanceToSegmentPx(pending, anchor, candidate) > tolerancePx) return false;
    for (const q of dropped) {
      if (distanceToSegmentPx(q, anchor, candidate) > tolerancePx) return false;
    }
    return true;
  }

  return {
    push(point) {
      if (same(point, lastSeen)) return [];
      lastSeen = point;
      if (pending === null) {
        pending = point;
        return [];
      }
      if (fits(point)) {
        dropped.push(pending);
        pending = point;
        return [];
      }
      const kept = keep(pending);
      pending = point;
      return [kept];
    },
    flush() {
      if (pending === null) return [];
      const kept = keep(pending);
      pending = null;
      return [kept];
    },
    end() {
      if (pending === null || same(pending, anchor)) {
        pending = null;
        return [];
      }
      const kept = keep(pending);
      pending = null;
      return [kept];
    },
    pending: () => pending,
    anchor: () => anchor,
  };
}

/** Every sample's distance to the nearest kept segment, in canvas pixels:
the promise above, checked by the tests over recorded strokes. */
export function maxThinningErrorPx(samples: StrokePoint[], kept: StrokePoint[]): number {
  if (kept.length === 0) return Infinity;
  let worst = 0;
  for (const sample of samples) {
    let best = Infinity;
    if (kept.length === 1) {
      best = distanceToSegmentPx(sample, kept[0], kept[0]);
    } else {
      for (let i = 0; i + 1 < kept.length; i++) {
        best = Math.min(best, distanceToSegmentPx(sample, kept[i], kept[i + 1]));
      }
    }
    worst = Math.max(worst, best);
  }
  return worst;
}
