import { distanceToSegmentSquared } from "./canvasGeometry.ts";
import type { Point } from "./canvasGeometry.ts";

export type Rgba = [number, number, number, number];

export function hexToRgba(hex: string): Rgba {
  const clean = hex.replace("#", "");
  const red = parseInt(clean.substring(0, 2), 16) || 0;
  const green = parseInt(clean.substring(2, 4), 16) || 0;
  const blue = parseInt(clean.substring(4, 6), 16) || 0;
  return [red, green, blue, 255];
}

export function colorsEqual(
  data: Uint8ClampedArray,
  index: number,
  target: Rgba,
): boolean {
  return data[index] === target[0]
    && data[index + 1] === target[1]
    && data[index + 2] === target[2]
    && data[index + 3] === target[3];
}

export const FLOOD_FILL_CHANNEL_TOLERANCE = 8;

export function colorsMatchForFill(
  data: Uint8ClampedArray,
  index: number,
  target: Rgba,
): boolean {
  return Math.abs(data[index] - target[0]) <= FLOOD_FILL_CHANNEL_TOLERANCE
    && Math.abs(data[index + 1] - target[1]) <= FLOOD_FILL_CHANNEL_TOLERANCE
    && Math.abs(data[index + 2] - target[2]) <= FLOOD_FILL_CHANNEL_TOLERANCE
    && Math.abs(data[index + 3] - target[3]) <= FLOOD_FILL_CHANNEL_TOLERANCE;
}

export function rasterizePath(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  points: Point[],
  radius: number,
  color: Rgba,
  closed: boolean,
): void {
  if (points.length === 0) return;
  const radiusSquared = radius * radius;
  const segmentCount = closed ? points.length : points.length - 1;

  for (let segment = 0; segment < segmentCount; segment++) {
    const a = points[segment];
    const b = points[(segment + 1) % points.length];
    const minX = Math.max(0, Math.floor(Math.min(a.x, b.x) - radius));
    const minY = Math.max(0, Math.floor(Math.min(a.y, b.y) - radius));
    const maxX = Math.min(width - 1, Math.ceil(Math.max(a.x, b.x) + radius));
    const maxY = Math.min(height - 1, Math.ceil(Math.max(a.y, b.y) + radius));
    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        if (
          distanceToSegmentSquared(x + 0.5, y + 0.5, a.x, a.y, b.x, b.y)
          <= radiusSquared
        ) {
          const index = (y * width + x) * 4;
          data[index] = color[0];
          data[index + 1] = color[1];
          data[index + 2] = color[2];
          data[index + 3] = color[3];
        }
      }
    }
  }
}

export function floodFillPixels(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  startX: number,
  startY: number,
  fillColor: Rgba,
): boolean {
  const startIndex = (startY * width + startX) * 4;
  if (colorsEqual(data, startIndex, fillColor)) return false;
  const target: Rgba = [
    data[startIndex],
    data[startIndex + 1],
    data[startIndex + 2],
    data[startIndex + 3],
  ];
  const visited = new Uint8Array(width * height);
  const stack: number[] = [startX, startY];

  while (stack.length > 0) {
    const y = stack.pop()!;
    const x = stack.pop()!;
    if (x < 0 || x >= width || y < 0 || y >= height) continue;
    const pixelIndex = y * width + x;
    if (visited[pixelIndex]) continue;
    const index = pixelIndex * 4;
    if (!colorsMatchForFill(data, index, target)) continue;
    visited[pixelIndex] = 1;
    data[index] = fillColor[0];
    data[index + 1] = fillColor[1];
    data[index + 2] = fillColor[2];
    data[index + 3] = fillColor[3];
    stack.push(
      x + 1, y,
      x - 1, y,
      x, y + 1,
      x, y - 1,
      x + 1, y + 1,
      x + 1, y - 1,
      x - 1, y + 1,
      x - 1, y - 1,
    );
  }
  return true;
}
