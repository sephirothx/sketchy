import { CANVAS_HEIGHT, CANVAS_WIDTH } from "./canvasHistory.ts";
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

export function toPixels(point: StrokePoint): Point {
  return {
    x: point.x * CANVAS_WIDTH,
    y: point.y * CANVAS_HEIGHT,
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
  return [
    { x: x + width / 2, y },
    { x, y: y + height },
    { x: x + width, y: y + height },
  ];
}
