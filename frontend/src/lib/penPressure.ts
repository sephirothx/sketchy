/** Turning a pen's pressure into the width of the line under it (#828).

**The selected size is the ceiling.** Full pressure draws the brush the drawer
picked and a lighter hand draws thinner, down to a floor. A pen therefore draws
nothing a mouse could not - any of these widths is a brush size a mouse user
can already select (R-DRAW-02) - and the toolbar's size still means what it
says: the widest the stroke will be.

**The floor is two pixels, never one.** The rasterizer paints a pixel when its
centre lies within the radius of the segment, and at a radius of half a pixel
most centres along a slanted line do not: a 1 px line is a row of holes, and a
flood fill beside it leaked across in 710 of 720 angles and offsets tried,
against none at 2 px. Two is also the smallest size the toolbar offers, so
nothing thinner has ever been drawn. Above that the floor is a quarter of the
brush.

**A brush has at most `MAX_WIDTH_LEVELS` widths.** Every change of width costs
two bytes on the wire and a point the thinner would otherwise have dropped
(the run boundary has to be kept), and one pixel is a sixth of a 6 px line but
a thirty-second of a 32 px one - a change nobody can see at the same price.
Stepping by a pixel, a 32 px brush changed width on half its points and cost
+36% on the drawer's uplink - no better than a width byte on every point;
with six widths it is +8%, and every brush on every recorded trace lands
between +4% and +11% (`benchmarks/path_widths.py`, which mirrors the
constants below). The levels are counted down from the brush, so
full pressure is exactly the selected size.

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
/** The thinnest a pen draws, in canvas pixels. See above: 1 px leaks fills. */
export const MIN_PEN_WIDTH = 2;
/** The floor as a share of the selected size. */
export const FLOOR_SHARE = 0.25;
/** How far toward the next level, as a share of the gap, the target must be to move the width. */
export const HYSTERESIS_STEPS = 0.75;
/** Pressure is raised to this before it is mapped: an ordinary writing hand
sits around a quarter to a half of a sensor's range, and mapped linearly would
spend the whole stroke near the floor. */
export const PRESSURE_GAMMA = 0.6;

const UNSUPPORTED_PRESSURE = 0.5;

export interface WidthLevels {
  floor: number;
  step: number;
  /** Ascending, ending on the brush itself. */
  widths: number[];
}

export function widthLevels(brush: number): WidthLevels {
  const floor = Math.min(brush, Math.max(MIN_PEN_WIDTH, Math.round(brush * FLOOR_SHARE)));
  const step = Math.max(1, Math.ceil((brush - floor) / (MAX_WIDTH_LEVELS - 1)));
  const widths: number[] = [];
  for (let width = brush; width > floor; width -= step) widths.unshift(width);
  widths.unshift(floor);
  return { floor, step, widths };
}

export interface PressureQuantizer {
  /** The width to draw at, given the latest pressure (0-1). */
  width(pressure: number): number;
}

export function createPressureQuantizer(brush: number): PressureQuantizer {
  const { floor, widths } = widthLevels(brush);
  let current: number | null = null;
  const nearest = (target: number): number => {
    let best = widths[0];
    for (const width of widths) {
      if (Math.abs(width - target) <= Math.abs(best - target)) best = width;
    }
    return best;
  };
  return {
    width(pressure) {
      const clamped = Number.isFinite(pressure) ? Math.min(1, Math.max(0, pressure)) : 0;
      const target = floor + clamped ** PRESSURE_GAMMA * (brush - floor);
      if (current === null) {
        current = nearest(target);
        return current;
      }
      // Measured against the gap to the next level on the target's side, not
      // a fixed step: the levels are counted down from the brush, so the gap
      // above the floor can be narrower than the rest, and the floor and the
      // brush itself must both stay reachable.
      const index = widths.indexOf(current);
      const neighbour = widths[index + Math.sign(target - current)];
      if (neighbour === undefined || neighbour === current) return current;
      if (Math.abs(target - current) < Math.abs(neighbour - current) * HYSTERESIS_STEPS) return current;
      current = nearest(target);
      return current;
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
