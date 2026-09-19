import { CANVAS_HEIGHT, CANVAS_WIDTH, wireToPixel } from "./canvasHistory.ts";
import type { ShapeType, StrokePoint } from "../types.ts";

export interface Point {
  x: number;
  y: number;
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** A normalized point as canvas pixels, on the wire's quarter-pixel grid:
the same floats the history decoder produces (`wireToPixel`). */
export function toPixels(point: StrokePoint): Point {
  return {
    x: wireToPixel(point.x, CANVAS_WIDTH),
    y: wireToPixel(point.y, CANVAS_HEIGHT),
  };
}

export function boundsFromPath(points: Point[], radius: number): Bounds {
  let minX = points[0].x;
  let minY = points[0].y;
  let maxX = points[0].x;
  let maxY = points[0].y;
  for (const point of points) {
    if (point.x < minX) minX = point.x;
    if (point.y < minY) minY = point.y;
    if (point.x > maxX) maxX = point.x;
    if (point.y > maxY) maxY = point.y;
  }
  const pad = radius + 1;
  return {
    minX: minX - pad,
    minY: minY - pad,
    maxX: maxX + pad,
    maxY: maxY + pad,
  };
}

export function distanceToSegmentSquared(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) {
    const ex = px - ax;
    const ey = py - ay;
    return ex * ex + ey * ey;
  }
  let t = ((px - ax) * dx + (py - ay) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  const ex = px - cx;
  const ey = py - cy;
  return ex * ex + ey * ey;
}

/** Whether pixel centre (px, py) is ink for a capsule of `radiusSquared`
around segment a-b. Inside is ink; exactly on the edge is ink on one side
only - below a horizontal segment, right of a vertical one - the half-open
rule a GPU applies to a pixel on a triangle's edge. So a stroke of width w
covers w pixels across wherever its centre sits: with a closed rule a line
centred on a half pixel was w + 1 thick, and on the drawer's canvas float
dust used to decide which edge rows it kept (#940).

The side comes from the segment's own geometry - the sign of the cross
product of its direction, taken one way round whichever way it was drawn,
with the offset to the pixel - and never from the projection's residual.
Live playback paints a segment in parts, split at interpolated points that
carry float dust; a tie's residual along the segment is then dust-sized and
of either sign, while the cross product is its length times the radius, far
from zero. Read off the residual, the parts dropped an edge pixel the whole
segment kept, and a fill after them saw another boundary (R-DRAW-01). */
/** A stretch of one segment, as a fraction of its length: what live playback
paints when a frame lands part way along it. */
export interface SegmentSpan {
  a: Point;
  b: Point;
  t0: number;
  t1: number;
}

export function capsuleCovers(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
  radiusSquared: number,
  t0 = 0,
  t1 = 1,
): boolean {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  // Only offsets from the segment's start, never an absolute position: the
  // drawer paints into a crop of the canvas with its points moved to the
  // crop's corner, a replay onto the whole canvas, and `px - (ax + t * dx)`
  // rounded differently at the two magnitudes - a pixel exactly the radius
  // away was ink on one and not the other (#949's probe). Moving by whole
  // pixels leaves every offset below bit for bit.
  const ux = px - ax;
  const uy = py - ay;
  const along = ux * dx + uy * dy;
  let t = lengthSquared === 0 ? 0 : along / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  // Painting a stretch t0..t1 of the segment - what live playback does, a
  // frame at a time - keeps the pixels whose nearest point on the *whole*
  // segment falls in it, decided exactly as the whole segment decides them.
  // Stretches that tile 0..1 then paint the whole segment's pixels and no
  // others, at any angle; a stretch painted as its own segment, between
  // interpolated points a float's width off the line, did not (R-DRAW-01).
  if (t < t0 || t > t1) return false;
  const cross = dx * uy - dy * ux;
  // Beside the segment the squared distance is cross² / length², compared
  // with both sides scaled by length² - no division, so on the wire's
  // quarter-pixel grid every product is exact and a pixel exactly on the
  // edge is a tie, for the half-open rule below, and not float dust.
  // Beyond an end it is the distance to that end.
  const pastEnd = lengthSquared !== 0 && along >= lengthSquared;
  const beyond = pastEnd || lengthSquared === 0 || along <= 0;
  const ex = pastEnd ? px - bx : ux;
  const ey = pastEnd ? py - by : uy;
  const squared = beyond ? ex * ex + ey * ey : cross * cross;
  const limit = beyond ? radiusSquared : radiusSquared * lengthSquared;
  if (squared !== limit) return squared < limit;
  // A dot - a tap, a single-point stroke - has no direction to take a side
  // from: its edge is ink below the centre, or right of it on the centre's
  // row, the same half as a line's, so a dot of width w spans w pixels
  // each way. (Both tests below are zero for it, which dropped every edge
  // pixel and made even widths a pixel narrow.)
  if (lengthSquared === 0) return ey > 0 || (ey === 0 && ex > 0);
  // One orientation for the direction, so a segment and its reverse agree:
  // pointing left, or straight down where it is vertical.
  const flip = dx > 0 || (dx === 0 && dy < 0) ? -1 : 1;
  const side = flip * cross;
  if (side !== 0) return side < 0;
  // On the segment's own line, beyond an end: the tip of a round cap.
  return flip * along < 0;
}

const ELLIPSE_OUTLINE_SEGMENTS = 96;

/** cos(i * 2π / 96) for the first quarter turn, i = 0..24, as literals.

Every painter has to place an ellipse's outline on the same floats, and
`Math.cos` and `Math.sin` cannot promise that: the language leaves them
approximate, so two browser engines may differ in the last bit, and even one
engine's `sin(θ)` and `cos(π/2 - θ)` do. Written out, the numbers are the same
wherever they are parsed; the other three quarters are the same numbers with
their signs and roles swapped, so the outline is exactly symmetric too. */
const QUARTER_COSINES = [
  1, 0.99785892323860348, 0.99144486137381038, 0.98078528040323043,
  0.96592582628906831, 0.94693012949510569, 0.92387953251128674, 0.89687274153268837,
  0.86602540378443871, 0.83146961230254524, 0.79335334029123517, 0.75183980747897738,
  0.70710678118654757, 0.65934581510006884, 0.60876142900872066, 0.5555702330196024,
  0.5, 0.44228869021900125, 0.38268343236508984, 0.3214394653031617,
  0.25881904510252074, 0.19509032201612833, 0.13052619222005171, 0.06540312923014327,
  0,
];
const QUARTER = ELLIPSE_OUTLINE_SEGMENTS / 4;

/** The cosine and sine of step `index` of the ellipse's outline. */
function outlineDirection(index: number): [number, number] {
  const step = index % QUARTER;
  const along = QUARTER_COSINES[step];
  const across = QUARTER_COSINES[QUARTER - step];
  switch (Math.floor(index / QUARTER)) {
    case 0: return [along, across];
    case 1: return [-across, along];
    case 2: return [-along, -across];
    default: return [across, -along];
  }
}

export function shapeOutlinePoints(
  from: StrokePoint,
  to: StrokePoint,
  shape: ShapeType,
): Point[] {
  const a = toPixels(from);
  const b = toPixels(to);
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const width = Math.abs(b.x - a.x);
  const height = Math.abs(b.y - a.y);

  if (shape === "rectangle") {
    return [
      { x, y },
      { x: x + width, y },
      { x: x + width, y: y + height },
      { x, y: y + height },
    ];
  }
  if (shape === "ellipse") {
    const centerX = x + width / 2;
    const centerY = y + height / 2;
    const radiusX = width / 2;
    const radiusY = height / 2;
    const points: Point[] = [];
    for (let index = 0; index < ELLIPSE_OUTLINE_SEGMENTS; index++) {
      const [cos, sin] = outlineDirection(index);
      points.push({
        x: centerX + radiusX * cos,
        y: centerY + radiusY * sin,
      });
    }
    return points;
  }
  // Both ends of the drag are corners (#787): it runs from one base corner to
  // the apex, and the base - on the start's row - is as long on the far side of
  // the apex as on the near one. Dragging downwards draws the triangle upside
  // down. The mirrored corner can fall outside the canvas, which the
  // rasterizers clip; the wire carries only the drag's own two points.
  return [
    a,
    b,
    { x: 2 * b.x - a.x, y: a.y },
  ];
}
