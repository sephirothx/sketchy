/** A path whose width changes along it (#828): keyframes, and the ramps between them.

A pen's pressure reaches the history as a few **width keyframes** - "the path
is this wide at this point" - and not as a width per point, which would cost a
byte on every point of every stroke (`penPressure.ts`, `widthKeyframes.ts`).
Between two keyframes the width is a straight line from the one to the other
**along the length of the path**, and no painter paints anything else: the
stretch is cut into pieces a pixel of width apart, each an equal share of its
length, so a line swells and tapers half a pixel a side at a time and never
steps. The path's start is a keyframe at the width it opened with; after the
last keyframe the width holds.

None of the pieces are on the wire or in the history. `expandWidthRamps`
derives them from the points and keyframes every client already holds, and
every painter goes through it - the drawer's own ink, a viewer's live
playback, the whole-path replay, the timelapse - so they still rasterize one
picture and a fill sees the same edges everywhere (R-DRAW-14). Two clients'
copies of a point differ by float dust: a live painter reaches a wire
coordinate as `packed / 3200 * 800`, one ulp off the replay's `packed / 4` for
about one coordinate in eight. Snapping only the *cuts* to the quarter-pixel
grid did not absorb that: a cut that lands exactly half-way between two grid
positions rounds either way on the dust, and a late joiner's ramp came out a
quarter pixel from the room's - one pixel of ink apart. So the path's own
points are snapped to that grid first, which is exact (every wire coordinate
is on it, and an ulp never reaches the next position), and everything after
is the same arithmetic on the same numbers everywhere.

And every *piece* is still one constant radius, which is what keeps painting a
segment in parts exact (`strokePlayback.ts`): playback paints spans of a
constant-radius segment, which tile it pixel for pixel, and a ramp is only
more capsules.
Pieces and runs meet at shared points, where each one's round cap covers the
join.

**What a live viewer may assume.** It paints a frame when it arrives, before
the next keyframe exists, so it paints whatever follows a frame's last
keyframe at that keyframe's width. That is only right if no later keyframe
ramps back across ink already painted, and the drawer's client guarantees it
(`useCanvasPointerInput.ts`): a keyframe of a new width is always preceded, in
the same frame or on the last point of the one before, by a keyframe to ramp
from. So a batch can be ramped from the point it joins, and come out as the
whole path will. */

import type { WidthChange } from "../types.ts";

export interface WidthRun {
  /** The run's segments join `points[from]` through `points[to]`. */
  from: number;
  to: number;
  width: number;
}

/** The runs of a path of `pointCount` points that starts at `width`. A change
at index `i` takes effect on the segment ending at point `i`, so the run
before it ends at point `i - 1`, which both share. A change on the very first
segment leaves the starting width a run of no segments - the dot a viewer
painted when the path opened - and it is kept, so a replay's raster is the
live one's. */
export function widthRuns(
  pointCount: number,
  width: number,
  widths: readonly WidthChange[] | undefined,
): WidthRun[] {
  const last = pointCount - 1;
  if (last < 1 || !widths || widths.length === 0) {
    return [{ from: 0, to: Math.max(0, last), width }];
  }
  const runs: WidthRun[] = [];
  let from = 0;
  let current = width;
  for (const [index, next] of widths) {
    const boundary = Math.min(last, Math.max(0, index - 1));
    if (boundary > from || runs.length === 0) runs.push({ from, to: boundary, width: current });
    from = Math.max(from, boundary);
    current = next;
  }
  if (last > from) runs.push({ from, to: last, width: current });
  return runs;
}

/** The width a path is at where it ends: what a batch joining it continues at. */
export function finalWidth(width: number, widths: readonly WidthChange[] | undefined): number {
  return widths?.at(-1)?.[1] ?? width;
}

/** The width of each of a batch's segments, given the width the path had
before it. Segment `i` is the one ending at `points[i]`. */
export function segmentWidths(
  pointCount: number,
  width: number,
  widths: readonly WidthChange[] | undefined,
): number[] {
  const result: number[] = [];
  let current = width;
  let next = 0;
  for (let index = 0; index < pointCount; index += 1) {
    if (widths && next < widths.length && widths[next][0] === index) {
      current = widths[next][1];
      next += 1;
    }
    result.push(current);
  }
  return result;
}

const RAMP_GRID = 4; // quarter pixels, the wire's own coordinate scale

interface PathPoint {
  x: number;
  y: number;
}

/** A point on the quarter-pixel grid its wire coordinates came from. */
function onGrid(point: PathPoint): PathPoint {
  return {
    x: Math.round(point.x * RAMP_GRID) / RAMP_GRID,
    y: Math.round(point.y * RAMP_GRID) / RAMP_GRID,
  };
}

export interface RampedPath {
  points: readonly PathPoint[];
  width: number;
  widths: WidthChange[] | undefined;
}

/** The same path with the width between every two keyframes ramped a pixel a
piece along the path's length. The result is a path like any other - more
points, and changes of a single pixel - so whatever paints a path paints this.
A path with no keyframes comes back as it was. */
export function expandWidthRamps(
  points: readonly PathPoint[],
  width: number,
  widths: readonly WidthChange[] | undefined,
): RampedPath {
  if (!widths || widths.length === 0 || points.length < 2) {
    return { points, width, widths: undefined };
  }
  points = points.map(onGrid);
  const out: PathPoint[] = [points[0]];
  const ramped: WidthChange[] = [];
  let fromIndex = 0;
  let fromWidth = width;
  for (const [toIndex, toWidth] of widths) {
    if (toIndex <= fromIndex || toIndex >= points.length) continue;
    const steps = Math.abs(toWidth - fromWidth);
    const lengths: number[] = [];
    let total = 0;
    for (let index = fromIndex; index < toIndex; index += 1) {
      // Not `Math.hypot`, which the language leaves approximate - two
      // engines may differ in its last bit, and a cut on a tie then rounds
      // to another quarter pixel. On the grid the squares and their sum are
      // exact, and `Math.sqrt` is correctly rounded everywhere.
      const dx = points[index + 1].x - points[index].x;
      const dy = points[index + 1].y - points[index].y;
      const length = Math.sqrt(dx * dx + dy * dy);
      lengths.push(length);
      total += length;
    }
    if (steps === 0 || total === 0) {
      // Nothing to ramp, or nowhere to: the width holds, or changes on the spot.
      for (let index = fromIndex + 1; index <= toIndex; index += 1) out.push(points[index]);
      if (steps !== 0) ramped.push([out.length - 1, toWidth]);
    } else {
      // One more piece than steps, so the stretch leaves at the width it came
      // in at and arrives at the width it is going to.
      const pieces = steps + 1;
      const direction = Math.sign(toWidth - fromWidth);
      let cut = 1;
      let walked = 0;
      for (let index = fromIndex; index < toIndex; index += 1) {
        const length = lengths[index - fromIndex];
        while (cut <= steps && (total * cut) / pieces <= walked + length) {
          const t = length > 0 ? ((total * cut) / pieces - walked) / length : 1;
          out.push({
            x: Math.round((points[index].x + (points[index + 1].x - points[index].x) * t) * RAMP_GRID) / RAMP_GRID,
            y: Math.round((points[index].y + (points[index + 1].y - points[index].y) * t) * RAMP_GRID) / RAMP_GRID,
          });
          // The piece that starts here ends at the next point pushed.
          ramped.push([out.length, fromWidth + direction * cut]);
          cut += 1;
        }
        walked += length;
        out.push(points[index + 1]);
      }
    }
    fromIndex = toIndex;
    fromWidth = toWidth;
  }
  for (let index = fromIndex + 1; index < points.length; index += 1) out.push(points[index]);
  return { points: out, width, widths: ramped.length > 0 ? ramped : undefined };
}

/** What to paint: the ramped path's runs, each a polyline at one width. */
export function rampedRuns(
  points: readonly PathPoint[],
  width: number,
  widths: readonly WidthChange[] | undefined,
): { points: PathPoint[]; width: number }[] {
  const path = expandWidthRamps(points, width, widths);
  return widthRuns(path.points.length, path.width, path.widths).map((run) => ({
    points: run.to === run.from
      ? [path.points[run.from], path.points[run.from]]
      : path.points.slice(run.from, run.to + 1),
    width: run.width,
  }));
}

/** A live batch, ramped, as the viewer's playback takes it: the points to
queue after `from`, the width of the segment ending at each, and the width the
path is left at. `widths` index into `points`, as they arrive on the wire;
`from` is where the path ends and `width` its last keyframe's width, which -
see the note above on what a viewer may assume - is what it is there. */
export function rampedBatch(
  from: PathPoint,
  points: readonly PathPoint[],
  width: number,
  widths: readonly WidthChange[] | undefined,
): { points: PathPoint[]; segmentWidths: number[]; finalWidth: number } {
  const path = expandWidthRamps(
    [from, ...points],
    width,
    widths?.map(([index, next]): WidthChange => [index + 1, next]),
  );
  const batch = path.points.slice(1);
  const each = segmentWidths(
    batch.length,
    width,
    path.widths?.map(([index, next]): WidthChange => [index - 1, next]),
  );
  return { points: batch, segmentWidths: each, finalWidth: finalWidth(width, widths) };
}
