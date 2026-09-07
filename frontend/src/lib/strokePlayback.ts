/** Playing a received stroke out over time instead of all at once (#559).

A viewer receives a stroke as batches, one per flush of the drawer's timer,
and used to paint each batch the moment it landed: a fast curve arrived as
visible facets, and a longer flush interval read as steps, which is why the
interval stayed at 40 ms while the byte curve said to raise it. This decouples
what the viewer *shows* from what it *received*. Each batch is scheduled to be
painted over the interval that follows its arrival - the time the next batch
takes to come - and every animation frame paints the part that has come due,
down to a fraction of a segment, so the viewer sees ink advance at the
screen's rate rather than the wire's.

Painting a segment in parts is exact: the rasterizer paints a capsule around
each segment, and a capsule split at a point on its own segment is the union
of the two halves, pixel for pixel. So the final raster is the raster of the
whole polyline, whatever the frame boundaries fell on.

Order is everything else. Only path points are spread over time; a path
start, a path end, a shape, a fill and a clear are *barriers*, applied when
the cursor reaches them, so a fill always sees the complete raster before it
and a new stroke never starts before the previous one has finished playing.
The queue is bounded: past `MAX_LAG_MS` of unplayed ink - a tab that was in the
background, a burst after jitter - the schedule is compressed so the viewer
catches up rather than drifting further behind, and a hidden tab drains
everything at once. A replay or a clear discards the queue: what follows
repaints from history.

Pure: `now` and the interval are injected, the painting is a callback, and
the tests drive it with a fake clock. */

import type { Point } from "./canvasGeometry";

/** How far behind the wire the presentation may fall before it catches up. */
export const MAX_LAG_MS = 250;

export interface SegmentStyle {
  radius: number;
  color: [number, number, number, number];
}

interface Segments {
  kind: "segments";
  /** The polyline, starting at the point the previous batch ended on. */
  points: Point[];
  style: SegmentStyle;
  dueStart: number;
  dueEnd: number;
  /** How much of the polyline is painted, in segments (fractional). */
  painted: number;
}

interface Barrier {
  kind: "barrier";
  run: () => void;
}

type Item = Segments | Barrier;

export interface StrokePlayback {
  /** Queue a batch of path points; `from` is where the path currently ends. */
  enqueueSegments(from: Point, points: Point[], style: SegmentStyle, now: number): void;
  /** Queue something that must run once everything before it is painted. */
  enqueueBarrier(run: () => void, now: number): void;
  /** Paint what has come due by `now`. Returns whether anything is left. */
  advance(now: number): boolean;
  /** Paint everything queued, at once. */
  drain(): void;
  /** Discard everything queued, unpainted. */
  cancel(): void;
  pending(): boolean;
}

function interpolate(a: Point, b: Point, t: number): Point {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

export function createStrokePlayback(options: {
  intervalMs: () => number;
  paint: (points: Point[], style: SegmentStyle) => void;
  maxLagMs?: number;
}): StrokePlayback {
  const maxLag = options.maxLagMs ?? MAX_LAG_MS;
  const queue: Item[] = [];

  function lastDueEnd(now: number): number {
    for (let index = queue.length - 1; index >= 0; index -= 1) {
      const item = queue[index];
      if (item.kind === "segments") return Math.max(now, item.dueEnd);
    }
    return now;
  }

  /** Paint the polyline from `item.painted` up to `upTo` segments. */
  function paintUpTo(item: Segments, upTo: number): void {
    const segmentCount = item.points.length - 1;
    const target = Math.min(upTo, segmentCount);
    if (target <= item.painted) return;
    const from = item.painted;
    const startIndex = Math.floor(from);
    const startPoint = from === startIndex
      ? item.points[startIndex]
      : interpolate(item.points[startIndex], item.points[startIndex + 1], from - startIndex);
    const endIndex = Math.floor(target);
    const points: Point[] = [startPoint];
    for (let index = startIndex + 1; index <= endIndex && index <= segmentCount; index += 1) {
      points.push(item.points[index]);
    }
    if (target > endIndex && endIndex < segmentCount) {
      points.push(interpolate(item.points[endIndex], item.points[endIndex + 1], target - endIndex));
    }
    if (points.length > 1) options.paint(points, item.style);
    item.painted = target;
  }

  function compress(now: number): void {
    // Everything due later than `now + maxLag` is pulled in, uniformly, so
    // the viewer catches up over the next interval rather than at a jump.
    const end = lastDueEnd(now);
    const excess = end - now - maxLag;
    if (excess <= 0) return;
    for (const item of queue) {
      if (item.kind !== "segments") continue;
      item.dueStart = Math.max(now, item.dueStart - excess);
      item.dueEnd = Math.max(now, item.dueEnd - excess);
    }
  }

  return {
    enqueueSegments(from, points, style, now) {
      if (points.length === 0) return;
      const start = lastDueEnd(now);
      queue.push({
        kind: "segments",
        points: [from, ...points],
        style,
        dueStart: start,
        dueEnd: start + options.intervalMs(),
        painted: 0,
      });
      compress(now);
    },
    enqueueBarrier(run, now) {
      if (queue.length === 0) {
        run();
        return;
      }
      queue.push({ kind: "barrier", run });
      compress(now);
    },
    advance(now) {
      while (queue.length > 0) {
        const item = queue[0];
        if (item.kind === "barrier") {
          queue.shift();
          item.run();
          continue;
        }
        const segmentCount = item.points.length - 1;
        const span = item.dueEnd - item.dueStart;
        const fraction = span <= 0 ? 1 : Math.min(1, Math.max(0, (now - item.dueStart) / span));
        paintUpTo(item, fraction * segmentCount);
        if (item.painted >= segmentCount) {
          queue.shift();
          continue;
        }
        return true;
      }
      return false;
    },
    drain() {
      while (queue.length > 0) {
        const item = queue.shift()!;
        if (item.kind === "barrier") item.run();
        else paintUpTo(item, item.points.length - 1);
      }
    },
    cancel() {
      queue.length = 0;
    },
    pending: () => queue.length > 0,
  };
}
