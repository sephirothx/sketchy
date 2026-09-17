/** Turning a pen's pressure into the width of the line under it (#828).

**The selected size is the ceiling.** Full pressure draws the brush the drawer
picked and a lighter hand draws thinner, down to a floor. A pen therefore draws
nothing a mouse could not - any of these widths is a brush size a mouse user
can already select (R-DRAW-02) - and the toolbar's size still means what it
says: the widest the stroke will be.

**The floor is two pixels, for every brush.** It was a quarter of the brush,
which gave a 32 px brush 8 px at its lightest: a pen could shade with it but
not draw a fine line without going to the slider. At 2 px the largest brush
spans everything the toolbar offers, and the size a drawer picks is how far
up the range a firm hand takes them. It is two and not one because the
rasterizer paints a pixel when its centre lies within the radius of the
segment, and at a radius of half a pixel most centres along a slanted line do
not: a 1 px line is a row of holes, and a flood fill beside it leaked across
in 710 of 720 angles and offsets tried, against none at 2 px. Two is also the
smallest size the toolbar offers, so nothing thinner has ever been drawn.

**A brush has at most `MAX_WIDTH_LEVELS` widths, spaced by ratio.** Every
change of width costs two bytes on the wire and a point the thinner would
otherwise have dropped (the run boundary has to be kept), so the widths are
few: stepping by a pixel, a 32 px brush changed width on two thirds of its
points and cost +50% on the drawer's uplink, worse than a width byte on every
point, where six widths cost +10% and every brush on every recorded trace
lands between +6% and +15% (`benchmarks/path_widths.py`, which mirrors the
constants below). And they are
spaced by ratio rather than by pixels - 2, 3, 6, 11, 18, 32 - because that is
how a change of width is seen: from 2 px to 3 is as visible as from 18 to 32,
and six even steps of 6 px would have jumped from 2 straight to 8 at the fine
end, where a pen's control matters most, and spent three levels between 20
and 32 that nobody could tell apart at a glance.

**Pressure moves along that same scale.** The share of the way from the floor
to the brush is taken in ratio too, so each level owns an equal band of
pressure and none is a sliver the hand passes through without being able to
stop in. Mapped in pixels instead, a 32 px brush's three finest widths would
together have had the lightest twentieth of the range.

**Full size comes before full pressure.** A sensor's 1.0 is as hard as the pen
can be pressed, which nobody draws at: `FULL_PRESSURE` of it already gives the
whole brush. Below that, pressure is raised to `PRESSURE_GAMMA`, a mild lift
because an ordinary writing hand sits in the lower half of a sensor's range.
Mild on purpose: at 0.6 the floor owned 2% of the range on a 32 px brush - a
fine line in name only - and at 0.8 every level below the brush has at least
5%, with the whole brush from about two thirds of the sensor's range up.

**Hysteresis.** A new width is taken only once the target is three quarters of
the way to the next level, not half: a hand held steady on the border of
two levels would otherwise flip between them on every sample.

**Which pens.** Only `pointerType === "pen"`. A mouse reports a constant 0.5
while a button is down and a finger reports 0, 1 or a guess from its contact
area; neither means anything. A pen with no pressure sensor *also* reports a
constant 0.5 - that is what the specification tells a browser to do - and
would draw every stroke at a middling width for no reason, so a pen is only
believed once it has reported some pressure that is not 0.5. A sensor's first
contact is a small number, so a real one is believed from its first stroke. */

/** How many widths a brush has between its floor and itself, inclusive. */
export const MAX_WIDTH_LEVELS = 6;
/** The thinnest a pen draws, in canvas pixels, whatever the brush. See above:
1 px leaks fills. */
export const MIN_PEN_WIDTH = 2;
/** The share of a sensor's range that already draws the whole brush. */
export const FULL_PRESSURE = 0.7;
/** How far toward the next level, as a share of the gap, the target must be to move the width. */
export const HYSTERESIS_STEPS = 0.75;
/** Pressure, as a share of `FULL_PRESSURE`, is raised to this before it is mapped. */
export const PRESSURE_GAMMA = 0.8;

const UNSUPPORTED_PRESSURE = 0.5;

export interface WidthLevels {
  floor: number;
  /** Ascending, from the floor to the brush itself. */
  widths: number[];
}

export function widthLevels(brush: number): WidthLevels {
  const floor = Math.min(brush, MIN_PEN_WIDTH);
  const widths: number[] = [];
  for (let level = 0; level < MAX_WIDTH_LEVELS; level += 1) {
    // Equal ratios from the floor to the brush, to the nearest pixel. A small
    // brush has fewer pixels than levels, so neighbours that round alike merge.
    const width = Math.round(floor * (brush / floor) ** (level / (MAX_WIDTH_LEVELS - 1)));
    if (width !== widths[widths.length - 1]) widths.push(width);
  }
  return { floor, widths };
}

/** Where a width sits between the floor (0) and the brush (1), by ratio. */
function scalePosition(width: number, floor: number, brush: number): number {
  return brush > floor ? Math.log(width / floor) / Math.log(brush / floor) : 0;
}

export interface PressureQuantizer {
  /** The width to draw at, given the latest pressure (0-1). */
  width(pressure: number): number;
}

export function createPressureQuantizer(brush: number): PressureQuantizer {
  const { floor, widths } = widthLevels(brush);
  const positions = widths.map((width) => scalePosition(width, floor, brush));
  let current: number | null = null;
  const nearest = (target: number): number => {
    let best = 0;
    for (let index = 0; index < positions.length; index += 1) {
      if (Math.abs(positions[index] - target) <= Math.abs(positions[best] - target)) best = index;
    }
    return best;
  };
  return {
    width(pressure) {
      const clamped = Number.isFinite(pressure) ? Math.min(1, Math.max(0, pressure / FULL_PRESSURE)) : 0;
      const target = clamped ** PRESSURE_GAMMA;
      if (current === null) {
        current = nearest(target);
        return widths[current];
      }
      // Measured against the gap to the next level on the target's side:
      // rounding to whole pixels leaves the gaps a little uneven, and the
      // floor and the brush itself must both stay reachable.
      const neighbour = current + Math.sign(target - positions[current]);
      if (neighbour < 0 || neighbour >= positions.length || neighbour === current) return widths[current];
      const gap = Math.abs(positions[neighbour] - positions[current]);
      if (Math.abs(target - positions[current]) < gap * HYSTERESIS_STEPS) return widths[current];
      current = nearest(target);
      return widths[current];
    },
  };
}

export interface PressureSource {
  /** Whether this pointer event's pressure should shape the stroke. */
  trusts(pointerType: string, pressure: number): boolean;
}

/** One per tab: whether this device's pen has shown a working sensor. */
export function createPressureSource(): PressureSource {
  let sensorSeen = false;
  return {
    trusts(pointerType, pressure) {
      if (pointerType !== "pen") return false;
      if (pressure > 0 && pressure !== UNSUPPORTED_PRESSURE) sensorSeen = true;
      return sensorSeen;
    },
  };
}
