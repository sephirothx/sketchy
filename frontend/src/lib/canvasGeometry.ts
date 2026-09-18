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
only - below the segment, or right of it where it runs vertical - the
half-open rule a GPU applies to a pixel on a triangle's edge. So a stroke of
width w covers w pixels across wherever its centre sits: with a closed rule a
line centred on a half pixel was w + 1 thick, and on the drawer's canvas
float dust used to decide which edge rows it kept (#940). */
export function capsuleCovers(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
  radiusSquared: number,
): boolean {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  let t = lengthSquared === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  const ex = px - (ax + t * dx);
  const ey = py - (ay + t * dy);
  const squared = ex * ex + ey * ey;
  if (squared !== radiusSquared) return squared < radiusSquared;
  return ey > 0 || (ey === 0 && ex > 0);
}

const ELLIPSE_OUTLINE_SEGMENTS = 96;

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
      const angle = (index / ELLIPSE_OUTLINE_SEGMENTS) * Math.PI * 2;
      points.push({
        x: centerX + radiusX * Math.cos(angle),
        y: centerY + radiusY * Math.sin(angle),
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
