import { capsuleCovers, type SegmentSpan } from "./canvasGeometry.ts";
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

let statusScratch = new Uint8Array(0);

/** A zeroed status buffer of at least `size` bytes, reused between fills. */
function scratchStatus(size: number): Uint8Array {
  if (statusScratch.length < size) {
    statusScratch = new Uint8Array(size);
  } else {
    statusScratch.fill(0, 0, size);
  }
  return statusScratch;
}

export function fillWhitePixels(data: Uint8ClampedArray): void {
  data.fill(255);
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
  // Painters agree to the pixel because they are handed the same numbers:
  // every wire coordinate arrives as `wireToPixel` makes it (#940). What
  // happens exactly on the edge is `capsuleCovers`'s half-open rule.
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
        if (capsuleCovers(x + 0.5, y + 0.5, a.x, a.y, b.x, b.y, radiusSquared)) {
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

/** The box a fill painted, for committing only that much of the canvas. */
export interface FillBounds {
  left: number;
  top: number;
  /** Exclusive. */
  right: number;
  /** Exclusive. */
  bottom: number;
}

/** The same four bytes, read as one 32-bit word in this machine's order - so
    comparing and writing words needs no assumption about endianness. */
function packRgba(color: Rgba): number {
  const bytes = new Uint8ClampedArray(color);
  return new Uint32Array(bytes.buffer)[0];
}

export function floodFillPixels(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  startX: number,
  startY: number,
  fillColor: Rgba,
  bounds?: FillBounds,
): boolean {
  if (startX < 0 || startX >= width || startY < 0 || startY >= height) {
    return false;
  }
  const startIndex = (startY * width + startX) * 4;
  if (colorsEqual(data, startIndex, fillColor)) return false;
  const target: Rgba = [
    data[startIndex],
    data[startIndex + 1],
    data[startIndex + 2],
    data[startIndex + 3],
  ];
  // A byte per pixel tracks unseen (0), queued (1), and filled (2) pixels, which
  // keeps fills safe when fillColor is tolerance-close to the target. At
  // 800×600 this fixed scratch buffer is 480 KB. Each pixel can be queued at
  // most once, and the stack stores one numeric seed per adjacent horizontal
  // run instead of eight coordinate pairs per visited pixel.
  //
  // Reused across calls: replaying a fill-heavy turn would otherwise allocate
  // and discard one of these per fill action.
  const status = scratchStatus(width * height);
  const stack: number[] = [startY * width + startX];
  status[startY * width + startX] = 1;

  // The pixels as words (#990): most pixels a fill meets are exactly the
  // colour it started on, and one word comparison settles those where four
  // per-channel tolerance checks used to; the tolerance test runs only on a
  // miss, and an exact match always passes it, so what is filled cannot
  // change. A run is written as words too. Falls back to bytes when the
  // buffer is not word-aligned, which an ImageData never is.
  const words = data.byteOffset % 4 === 0
    ? new Uint32Array(data.buffer, data.byteOffset, data.length >> 2)
    : null;
  const targetWord = words ? words[startIndex >> 2] : 0;
  const fillWord = words ? packRgba(fillColor) : 0;

  const matchesTarget = words
    ? (pixelIndex: number): boolean => (
      status[pixelIndex] !== 2
      && (words[pixelIndex] === targetWord || colorsMatchForFill(data, pixelIndex * 4, target))
    )
    : (pixelIndex: number): boolean => (
      status[pixelIndex] !== 2
      && colorsMatchForFill(data, pixelIndex * 4, target)
    );

  const fillRun = (from: number, to: number): void => {
    status.fill(2, from, to + 1);
    if (words) {
      words.fill(fillWord, from, to + 1);
      return;
    }
    for (let pixelIndex = from; pixelIndex <= to; pixelIndex++) {
      const index = pixelIndex * 4;
      data[index] = fillColor[0];
      data[index + 1] = fillColor[1];
      data[index + 2] = fillColor[2];
      data[index + 3] = fillColor[3];
    }
  };

  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;

  const queueAdjacentRuns = (
    y: number,
    left: number,
    right: number,
  ): void => {
    if (y < 0 || y >= height) return;
    const rowOffset = y * width;
    const scanLeft = Math.max(0, left - 1);
    const scanRight = Math.min(width - 1, right + 1);
    let insideRun = false;
    for (let x = scanLeft; x <= scanRight; x++) {
      const pixelIndex = rowOffset + x;
      if (matchesTarget(pixelIndex)) {
        if (!insideRun && status[pixelIndex] === 0) {
          status[pixelIndex] = 1;
          stack.push(pixelIndex);
        }
        insideRun = true;
      } else {
        insideRun = false;
      }
    }
  };

  while (stack.length > 0) {
    const seed = stack.pop()!;
    if (!matchesTarget(seed)) continue;
    const y = Math.floor(seed / width);
    const seedX = seed - y * width;
    const rowOffset = y * width;

    let left = seedX;
    while (left > 0 && matchesTarget(rowOffset + left - 1)) left--;
    let right = seedX;
    while (right + 1 < width && matchesTarget(rowOffset + right + 1)) right++;

    fillRun(rowOffset + left, rowOffset + right);
    if (left < minX) minX = left;
    if (right > maxX) maxX = right;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;

    // Expand the adjacent-row scan by one pixel on both sides to preserve the
    // existing eight-connected diagonal behaviour.
    queueAdjacentRuns(y - 1, left, right);
    queueAdjacentRuns(y + 1, left, right);
  }
  if (bounds) {
    bounds.left = minX;
    bounds.top = minY;
    bounds.right = maxX + 1;
    bounds.bottom = maxY + 1;
  }
  return true;
}

/** Paint stretches of segments (`SegmentSpan`), each pixel decided against
its whole segment, so stretches that tile a segment paint exactly what the
segment painted whole would (R-DRAW-01). */
export function rasterizeSpans(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  spans: readonly SegmentSpan[],
  radius: number,
  color: Rgba,
): void {
  const radiusSquared = radius * radius;
  for (const { a, b, t0, t1 } of spans) {
    const fromX = a.x + (b.x - a.x) * t0;
    const fromY = a.y + (b.y - a.y) * t0;
    const toX = a.x + (b.x - a.x) * t1;
    const toY = a.y + (b.y - a.y) * t1;
    // One pixel of slack on the box: its corners are interpolated, and a
    // pixel the span owns must not be clipped by a float's width.
    const minX = Math.max(0, Math.floor(Math.min(fromX, toX) - radius) - 1);
    const minY = Math.max(0, Math.floor(Math.min(fromY, toY) - radius) - 1);
    const maxX = Math.min(width - 1, Math.ceil(Math.max(fromX, toX) + radius) + 1);
    const maxY = Math.min(height - 1, Math.ceil(Math.max(fromY, toY) + radius) + 1);
    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        if (capsuleCovers(x + 0.5, y + 0.5, a.x, a.y, b.x, b.y, radiusSquared, t0, t1)) {
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
