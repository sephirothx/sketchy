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
30 px one. And the share itself grows with the width - 15% up to 8 px, 25%
from 16 px - because the wide strokes are where the keyframes were: a wobble
of the hand is more pixels there, the 32 px brush sent two and a half times
the keyframes of the 12, and a fifth of a fat line's width is the hardest
error there is to see. Measured with the smoothing in `penPressure.ts`
(`benchmarks/path_widths.py`), that took the largest brush from +15-18% on
the drawer's uplink to +8-10%, and from half again as fast through the
turn's drawing limit to a quarter.

**Except at the ends of the brush's range, where it is exact.** Full pressure
draws the selected size and a resting pen draws the floor: those are promises
(`penPressure.ts`), and a tolerance of a quarter of 32 px would let a stroke
held at full pressure be drawn at 26. A sample that rounds to the brush or to
the floor is therefore held to under half a pixel, which is to say to the
pixel - and the tolerance **tightens toward that gradually**, never looser
than half a pixel plus the distance left to the end. Dropping from 8 px to
half of one between two samples was tried first, and put a shoulder back
exactly where the line reaches its full width: the ramp was allowed to arrive
eight pixels short and then had one sample to make them up. It costs a few
points of the saving, and the line is as wide as the slider says. */

/** How far a sample's width may be from the ramp drawn in its place: at least
a pixel, and a share of the width that loosens as the line gets fat. */
export const WIDTH_TOLERANCE_PX = 1;
export const FINE_TOLERANCE_SHARE = 0.15;
export const WIDE_TOLERANCE_SHARE = 0.25;
/** Up to the first the fine share applies; from the second, the wide one. */
export const TOLERANCE_WIDENS_BETWEEN = [8, 16] as const;

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

/** How far the width may have drifted from the last keyframe when a frame
goes out with nothing to say about it, as a share of `widthTolerance`. A
viewer paints that frame flat, and the drift is made up by the ramp that
follows, so a whole tolerance of it - a quarter of a fat line - shows as a
kink at the frame boundary. Half of one does not, and costs a keyframe on
some frames that would have had none. */
export const QUIET_FRAME_SHARE = 0.5;

/** Under half a pixel: the ramp and the sample round to the same width. */
export const EXACT_TOLERANCE_PX = 0.49;

export function widthTolerance(width: number, range: { floor: number; brush: number }): number {
  const toEnd = Math.max(0, Math.min(range.brush - width, width - range.floor));
  const [fine, wide] = TOLERANCE_WIDENS_BETWEEN;
  const along = Math.min(1, Math.max(0, (width - fine) / (wide - fine)));
  const share = FINE_TOLERANCE_SHARE + (WIDE_TOLERANCE_SHARE - FINE_TOLERANCE_SHARE) * along;
  return Math.min(Math.max(WIDTH_TOLERANCE_PX, width * share), EXACT_TOLERANCE_PX + toEnd);
}

export function createWidthThinner(start: WidthSample, range: { floor: number; brush: number }): WidthThinner {
  let anchor = start;
  let pending: WidthSample | null = null;
  let passed: WidthSample[] = [];

  function fits(candidate: WidthSample): boolean {
    const span = candidate.at - anchor.at;
    const onRamp = (sample: WidthSample) =>
      anchor.width + (candidate.width - anchor.width) * (span > 0 ? (sample.at - anchor.at) / span : 1);
    if (pending && Math.abs(pending.width - onRamp(pending)) > widthTolerance(pending.width, range)) return false;
    for (const sample of passed) {
      if (Math.abs(sample.width - onRamp(sample)) > widthTolerance(sample.width, range)) return false;
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
