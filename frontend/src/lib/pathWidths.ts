/** A path whose width changes along it (#828), as runs of one width each.

A pen's pressure reaches the history as width changes between points, so a
path is a sequence of runs rather than one polyline at one width. Every
painter works a run at a time - the whole-path rasterizer, the replay's
growing stroke, the viewer's live playback - because a run is exactly what
they painted before: consecutive segments at one constant radius. That is
also what keeps a segment painted in parts exact (`strokePlayback.ts`): no
segment ever tapers. Runs meet at a shared point, where each one's round cap
covers the join. */

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
