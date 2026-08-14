import { CANVAS_HEIGHT, CANVAS_WIDTH } from "./canvasHistory.ts";
import { boundsFromPath, shapeOutlinePoints, toPixels } from "./canvasGeometry.ts";
import type { Point } from "./canvasGeometry.ts";
import { floodFillPixels, hexToRgba, rasterizePath as rasterizePixelPath } from "./canvasPixels.ts";
import type {
  ShapeType,
  StrokeFillPayload,
  StrokePoint,
} from "../types.ts";

export function fillWhite(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
): void {
  context.save();
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.restore();
}

export function drawShapeOutline(
  context: CanvasRenderingContext2D,
  from: StrokePoint,
  to: StrokePoint,
  shape: ShapeType,
  strokeColor: string,
  strokeWidth: number,
): void {
  const a = toPixels(from);
  const b = toPixels(to);
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const width = Math.abs(b.x - a.x);
  const height = Math.abs(b.y - a.y);

  context.strokeStyle = strokeColor;
  context.lineWidth = strokeWidth;
  context.beginPath();
  if (shape === "rectangle") {
    context.rect(x, y, width, height);
  } else if (shape === "ellipse") {
    context.ellipse(
      x + width / 2,
      y + height / 2,
      width / 2,
      height / 2,
      0,
      0,
      Math.PI * 2,
    );
  } else {
    context.moveTo(x + width / 2, y);
    context.lineTo(x, y + height);
    context.lineTo(x + width, y + height);
    context.closePath();
  }
  context.stroke();
}

export function rasterizePath(
  context: CanvasRenderingContext2D,
  points: Point[],
  radius: number,
  color: [number, number, number, number],
  closed: boolean,
): void {
  if (points.length === 0) return;
  const bounds = boundsFromPath(points, radius);
  const x = Math.max(0, Math.floor(bounds.minX));
  const y = Math.max(0, Math.floor(bounds.minY));
  const right = Math.min(CANVAS_WIDTH, Math.ceil(bounds.maxX));
  const bottom = Math.min(CANVAS_HEIGHT, Math.ceil(bounds.maxY));
  const width = right - x;
  const height = bottom - y;
  if (width <= 0 || height <= 0) return;

  const imageData = context.getImageData(x, y, width, height);
  const localPoints = points.map((point) => ({ x: point.x - x, y: point.y - y }));
  rasterizePixelPath(
    imageData.data,
    width,
    height,
    localPoints,
    radius,
    color,
    closed,
  );
  context.putImageData(imageData, x, y);
}

export function rasterizePolyline(
  context: CanvasRenderingContext2D,
  points: Point[],
  radius: number,
  color: [number, number, number, number],
): void {
  if (points.length === 0) return;
  rasterizePath(context, points, radius, color, false);
}

export function drawShapeOutlinePixels(
  context: CanvasRenderingContext2D,
  from: StrokePoint,
  to: StrokePoint,
  shape: ShapeType,
  strokeColor: string,
  strokeWidth: number,
): void {
  rasterizePath(
    context,
    shapeOutlinePoints(from, to, shape),
    strokeWidth / 2,
    hexToRgba(strokeColor),
    true,
  );
}

export function applyFillAtPixel(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  color: string,
): boolean {
  if (x < 0 || x >= CANVAS_WIDTH || y < 0 || y >= CANVAS_HEIGHT) return false;
  const imageData = context.getImageData(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
  if (!floodFillPixels(
    imageData.data,
    imageData.width,
    imageData.height,
    x,
    y,
    hexToRgba(color),
  )) return false;
  context.putImageData(imageData, 0, 0);
  return true;
}

export function applyFillAction(
  context: CanvasRenderingContext2D,
  payload: StrokeFillPayload,
): boolean {
  return applyFillAtPixel(
    context,
    Math.floor(payload.x * CANVAS_WIDTH),
    Math.floor(payload.y * CANVAS_HEIGHT),
    payload.color,
  );
}
