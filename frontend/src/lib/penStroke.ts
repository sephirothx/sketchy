/** One pen stroke's width keyframes, as the drawer's client places them (#828).

Between the pointer hook, which knows about events and canvases, and the
helpers that are each about one thing (`widthKeyframes.ts` picks keyframes,
`pathWidths.ts` ramps between them), something has to hold a stroke's state:
which frame a keyframe goes in, what the drawer's own canvas may already
paint, and the one promise the viewers rely on. This is that, kept free of the
DOM so the promise can be tested.

**The promise.** A viewer paints a frame when it arrives, and paints whatever
follows the frame's last keyframe at that keyframe's width, because the next
keyframe does not exist yet. A later keyframe of another width would ramp back
from the previous one - across ink the viewer has already painted flat. So a
keyframe of a new width is never sent unless the keyframe it ramps from is in
the same frame or on the last point of the frame before. Two rules keep that:

- When a frame is about to go and the width is part way through a change, its
  last point gets a keyframe at the width it has reached. The ramp carries on
  from there in the next frame.
- When a change begins after a stretch with no keyframes - the hand held
  steady, frames went out with nothing to say - the frame it begins in gets a
  **hold**: a keyframe at the *old* width on its first point, for the change
  to ramp from. If the change's keyframe is itself that first point there is
  nothing before it to hold, so it becomes the hold and the change is picked
  up at the next keyframe, a point later.

**The drawer's own canvas** is painted by the same rule as everyone's, which
means it cannot paint a kept point until the keyframe that decides its width
exists: at the next keyframe, or at the next flush, 80 ms at most. Until then
those points are *undetermined*, and the hook shows them on the preview layer
at the width they are heading for. */

import { rampedRuns } from "./pathWidths.ts";
import type { WidthChange } from "../types.ts";

interface PixelPoint {
  x: number;
  y: number;
}

export interface PaintRun {
  points: PixelPoint[];
  width: number;
}

/** Where the last keyframe is, as far as ramping from it goes. */
type Reach = "frame" | "previous-frame-end" | "earlier";

export class PenStroke {
  /** The last keyframe's width: what the path holds until the next one. */
  private keyWidth: number;
  private sentKeyWidth: number;
  private reach: Reach = "previous-frame-end";
  /** The kept points since the last keyframe, starting with its own. */
  private undetermined: PixelPoint[];
  /** Where in `undetermined` a hold was placed, if one was. */
  private frameFirst: PixelPoint | null = null;
  private frameLength = 0;
  private frameWidths: WidthChange[] = [];

  constructor(start: PixelPoint, startWidth: number) {
    // The start is a keyframe - the width in the path's header - and viewers
    // have painted nothing but its dot, so the first change may ramp from it.
    this.keyWidth = startWidth;
    this.sentKeyWidth = startWidth;
    this.undetermined = [start];
  }

  get width(): number {
    return this.keyWidth;
  }

  /** A kept point joins the frame being built, with a keyframe if it is one.
  Returns what may now be painted, and whether the keyframe had to become a
  hold - in which case the width the caller asked for was not placed. */
  accept(point: PixelPoint, key?: number): { runs: PaintRun[]; held: boolean } {
    if (this.frameLength === 0) this.frameFirst = point;
    this.frameLength += 1;
    this.undetermined.push(point);
    return key === undefined ? { runs: [], held: false } : this.keyLast(key)!;
  }

  /** A keyframe on the last point accepted, which is how one lands on a point
  that was kept for its own sake a moment ago. Null when that point has left
  in a frame already, or has a keyframe: there is then nowhere to put it. */
  keyLast(key: number): { runs: PaintRun[]; held: boolean } | null {
    const index = this.frameLength - 1;
    if (index < 0 || this.frameWidths.at(-1)?.[0] === index) return null;
    if (key !== this.keyWidth && this.reach === "earlier") {
      if (index === 0) {
        const runs = this.commit([]);
        this.place(index, this.keyWidth);
        return { runs, held: true };
      }
      // A hold on the frame's first point; the change ramps from there.
      this.frameWidths.push([0, this.keyWidth]);
      const holdAt = this.undetermined.indexOf(this.frameFirst!);
      const runs = this.commit([[holdAt, this.keyWidth], [this.undetermined.length - 1, key]]);
      this.place(index, key);
      return { runs, held: false };
    }
    const runs = this.commit([[this.undetermined.length - 1, key]]);
    this.place(index, key);
    return { runs, held: false };
  }

  /** The frame is about to go. `width` is what the pen is asking for now: if
  the path is part way to it, the frame's last point says how far it got.
  `placed` tells the caller a keyframe went there. */
  flush(width: number): { runs: PaintRun[]; placed: boolean } {
    if (this.frameLength === 0) return { runs: [], placed: false };
    if (width !== this.keyWidth) {
      const keyed = this.keyLast(width);
      if (keyed) return { runs: keyed.runs, placed: !keyed.held };
    }
    return { runs: this.commit([]), placed: false };
  }

  /** The frame's keyframes, for the encoder; the next frame starts empty. */
  takeFrame(): WidthChange[] {
    const widths = this.frameWidths;
    const endsOnKey = widths.at(-1)?.[0] === this.frameLength - 1;
    if (this.frameLength > 0) this.reach = endsOnKey ? "previous-frame-end" : "earlier";
    this.frameWidths = [];
    this.frameLength = 0;
    this.frameFirst = null;
    return widths;
  }

  /** The frame did not go (refused whole): the server's path is where it was. */
  frameRefused(): void {
    this.keyWidth = this.sentKeyWidth;
    this.reach = "earlier";
  }

  frameSent(): void {
    this.sentKeyWidth = this.keyWidth;
  }

  /** For the preview layer: the undetermined points and the sample under the
  pen, heading for `width`. Replaced by real ink at the next keyframe or flush. */
  provisional(pending: PixelPoint | null, width: number): PaintRun[] {
    const points = pending ? [...this.undetermined, pending] : this.undetermined;
    if (points.length < 2) return [];
    return rampedRuns(points, this.keyWidth, width === this.keyWidth ? undefined : [[points.length - 1, width]]);
  }

  private place(index: number, width: number): void {
    this.frameWidths.push([index, width]);
    this.keyWidth = width;
    this.reach = "frame";
  }

  /** Paint the undetermined points - ramped through `widths`, flat after the
  last of them - and start over from the last point. */
  private commit(widths: WidthChange[]): PaintRun[] {
    const points = this.undetermined;
    if (points.length < 2) return [];
    const runs = rampedRuns(points, this.keyWidth, widths.length > 0 ? widths : undefined);
    this.undetermined = [points[points.length - 1]];
    return runs;
  }
}
