/** Choosing which of a pen stroke's widths to send (#828).

The width a pen asks for changes with every sample, and sending it with every
point would cost a byte on each (`benchmarks/path_widths.py`). But a hand's
pressure is a smooth curve - it swells over a tenth of a second, holds, and
eases off - and a smooth curve is well described by a few points on it with
straight lines between. So the stroke's width travels as **keyframes**, and
every painter ramps the width from one to the next along the path
(`pathWidths.ts`). A swell from 2 px to 32 that six fixed levels drew as five
visible steps is one ramp, and usually two keyframes.

This picks them, and it is the point thinner over again (`pointThinning.ts`)
with the path's length for x and the width for y: an **anchor** (the last
keyframe), one **pending** sample, and every sample passed over since the
anchor. A new sample replaces the pending one only while a straight ramp from
the anchor to it stays within the tolerance of *every* sample passed over;
when it would not, the pending sample becomes a keyframe. So no sample's width
is ever further from the ramp that replaced it than the tolerance, however
many were passed over - the error cannot accumulate.

The tolerance is a share of the width, with a floor of a pixel, because that
is how a width is seen: a pixel matters on a 4 px line and is nothing on a
30 px one, and it is the wide strokes whose sensor noise would otherwise be
chased keyframe by keyframe. */

/** How far a sample's width may be from the ramp drawn in its place. */
export const WIDTH_TOLERANCE_PX = 1;
export const WIDTH_TOLERANCE_SHARE = 0.15;

export interface WidthSample {
  /** How far along the path, in canvas pixels. */
  at: number;
  width: number;
}

export interface WidthThinner {
  /** Offer the next sample. True when the sample *before* it - the pending
  one - has to be a keyframe; it is then the new anchor. */
  push(sample: WidthSample): boolean;
  /** The sample that would be the next keyframe, or null right after one. */
  pending(): WidthSample | null;
  /** A keyframe was placed here by somebody else - a flush, the stroke's
  end, a keyframe the caller had to move: carry on from it. */
  anchorAt(sample: WidthSample): void;
}

export function widthTolerance(width: number): number {
  return Math.max(WIDTH_TOLERANCE_PX, width * WIDTH_TOLERANCE_SHARE);
}

export function createWidthThinner(start: WidthSample): WidthThinner {
  let anchor = start;
  let pending: WidthSample | null = null;
  let passed: WidthSample[] = [];

  function fits(candidate: WidthSample): boolean {
    const span = candidate.at - anchor.at;
    const onRamp = (sample: WidthSample) =>
      anchor.width + (candidate.width - anchor.width) * (span > 0 ? (sample.at - anchor.at) / span : 1);
    if (pending && Math.abs(pending.width - onRamp(pending)) > widthTolerance(pending.width)) return false;
    for (const sample of passed) {
      if (Math.abs(sample.width - onRamp(sample)) > widthTolerance(sample.width)) return false;
    }
    return true;
  }

  return {
    push(sample) {
      if (pending === null) {
        pending = sample;
        return false;
      }
      if (fits(sample)) {
        passed.push(pending);
        pending = sample;
        return false;
      }
      anchor = pending;
      passed = [];
      pending = sample;
      return true;
    },
    pending: () => pending,
    anchorAt(sample) {
      anchor = sample;
      passed = [];
      pending = null;
    },
  };
}
