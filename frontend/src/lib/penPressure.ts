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

**Pressure moves the width by ratio, not by pixels.** From 2 px to 3 is as
visible as from 18 to 32, so equal shares of pressure multiply the width by
equal amounts: half way is 8 px on the 32 px brush, not 17. Mapped in pixels,
everything finer than 8 px on that brush would have lived in the lightest
fifth of the range, where a hand cannot stop.

**Full size comes before full pressure.** A sensor's 1.0 is as hard as the pen
can be pressed, which nobody draws at: `FULL_PRESSURE` of it already gives the
whole brush. Below that, pressure is raised to `PRESSURE_GAMMA`, a mild lift
because an ordinary writing hand sits in the lower half of a sensor's range.

**What this returns is continuous.** It used to be one of six levels per brush,
because every change of width costs bytes; but however the levels were chosen
and however their joins were drawn, a line that holds 11 px and then holds
18 px has a shoulder. What is sent now is a few keyframes of this curve, with
the width ramped between them (`widthKeyframes.ts`, `pathWidths.ts`), which
costs about what the levels did and has no levels to see.

**Which pens.** Only `pointerType === "pen"`. A mouse reports a constant 0.5
while a button is down and a finger reports 0, 1 or a guess from its contact
area; neither means anything. A pen with no pressure sensor *also* reports a
constant 0.5 - that is what the specification tells a browser to do - and
would draw every stroke at a middling width for no reason, so a pen is only
believed once it has reported some pressure that is not 0.5. A sensor's first
contact is a small number, so a real one is believed from its first stroke. */

/** The thinnest a pen draws, in canvas pixels, whatever the brush. See above:
1 px leaks fills. */
export const MIN_PEN_WIDTH = 2;
/** The share of a sensor's range that already draws the whole brush. */
export const FULL_PRESSURE = 0.7;
/** Pressure, as a share of `FULL_PRESSURE`, is raised to this before it is mapped. */
export const PRESSURE_GAMMA = 0.8;

const UNSUPPORTED_PRESSURE = 0.5;

/** The width a pressure (0-1) asks of a brush, in pixels and not yet whole:
between the floor and the brush, by ratio. */
export function targetWidth(pressure: number, brush: number): number {
  const floor = Math.min(brush, MIN_PEN_WIDTH);
  if (brush <= floor) return brush;
  const share = Number.isFinite(pressure) ? Math.min(1, Math.max(0, pressure / FULL_PRESSURE)) : 0;
  return floor * (brush / floor) ** (share ** PRESSURE_GAMMA);
}

/** A keyframe's width: whole pixels, as the wire carries them, inside the brush's range. */
export function wholeWidth(width: number, brush: number): number {
  return Math.min(brush, Math.max(Math.min(brush, MIN_PEN_WIDTH), Math.round(width)));
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
