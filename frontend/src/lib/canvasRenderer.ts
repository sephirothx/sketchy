import { CANVAS_HEIGHT, CANVAS_WIDTH } from "./canvasHistory.ts";
import type { DecodedCanvasAction } from "./canvasHistory.ts";
import { boundsFromPath, shapeOutlinePoints, toPixels } from "./canvasGeometry.ts";
import type { Point, SegmentSpan } from "./canvasGeometry.ts";
import { replayStroke } from "./replay.ts";
import type { ReplayStroke } from "./replay.ts";
import { rampedRuns, widthRuns } from "./pathWidths.ts";
import {
  fillWhitePixels,
  floodFillPixels,
  hexToRgba,
  rasterizeSpans,
  rasterizePath as rasterizePixelPath,
} from "./canvasPixels.ts";
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
    // The triangle depends on which way the drag went, so the preview takes
    // its corners from the same place the committed shape does.
    const [first, ...rest] = shapeOutlinePoints(from, to, shape);
    context.moveTo(first.x, first.y);
    for (const point of rest) context.lineTo(point.x, point.y);
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

/** Paint stretches of segments onto the canvas, as live playback hands them
over (`rasterizeSpans`): the pixels the whole segments would have, a frame at
a time. */
export function rasterizeSegmentSpans(
  context: CanvasRenderingContext2D,
  spans: readonly SegmentSpan[],
  radius: number,
  color: [number, number, number, number],
): void {
  if (spans.length === 0) return;
  const ends = spans.flatMap(({ a, b, t0, t1 }) => [
    { x: a.x + (b.x - a.x) * t0, y: a.y + (b.y - a.y) * t0 },
    { x: a.x + (b.x - a.x) * t1, y: a.y + (b.y - a.y) * t1 },
  ]);
  const bounds = boundsFromPath(ends, radius + 1);
  const x = Math.max(0, Math.floor(bounds.minX));
  const y = Math.max(0, Math.floor(bounds.minY));
  const right = Math.min(CANVAS_WIDTH, Math.ceil(bounds.maxX));
  const bottom = Math.min(CANVAS_HEIGHT, Math.ceil(bounds.maxY));
  if (right - x <= 0 || bottom - y <= 0) return;
  const imageData = context.getImageData(x, y, right - x, bottom - y);
  // Moved by whole pixels, which is exact for quarter-pixel coordinates, so
  // each decision is the one the whole canvas would make.
  const local = spans.map(({ a, b, t0, t1 }) => ({
    a: { x: a.x - x, y: a.y - y },
    b: { x: b.x - x, y: b.y - y },
    t0,
    t1,
  }));
  rasterizeSpans(imageData.data, right - x, bottom - y, local, radius, color);
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
  // Reads the canvas: a live fill spreads through the strokes already on it.
  // Only a full replay, which starts from white, can skip the readback.
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

/** Apply one action to a pixel buffer that already holds everything before it. */
export function applyCanvasAction(
  pixels: Uint8ClampedArray,
  action: DecodedCanvasAction,
): void {
  if (action.kind === "path" && action.points.length > 0) {
    const color = hexToRgba(action.color);
    // One run for a path at one width, which is every path not drawn with a
    // pressure-sensitive pen (#828); for one that was, its changes ramped.
    for (const run of rampedRuns(action.points, action.width, action.widths)) {
      rasterizePixelPath(pixels, CANVAS_WIDTH, CANVAS_HEIGHT, run.points, run.width / 2, color, false);
    }
  } else if (action.kind === "shape") {
    rasterizePixelPath(
      pixels,
      CANVAS_WIDTH,
      CANVAS_HEIGHT,
      shapeOutlinePoints(action.payload.from, action.payload.to, action.payload.shape),
      action.payload.width / 2,
      hexToRgba(action.payload.color),
      true,
    );
  } else if (action.kind === "fill") {
    if (
      action.x >= 0 && action.x < CANVAS_WIDTH
      && action.y >= 0 && action.y < CANVAS_HEIGHT
    ) {
      floodFillPixels(
        pixels,
        CANVAS_WIDTH,
        CANVAS_HEIGHT,
        action.x,
        action.y,
        hexToRgba(action.color),
      );
    }
  } else if (action.kind === "clear") {
    fillWhitePixels(pixels);
  }
}

/**
 * Apply the stretch `from..to` of a stroke, as it grew: what a replay draws
 * frame by frame. The ends are positions along the stroke in points,
 * fractional between two of them, so a stroke of three long points still
 * grows smoothly rather than in three jumps. Round caps make the joins
 * seamless, and an opaque stroke drawn twice over the same pixels is the
 * same stroke, so a stretch may overlap the one before it. A shape's
 * outline is a stroke like any other here, closed by its caller.
 */
export function applyCanvasStrokeSpan(
  pixels: Uint8ClampedArray,
  stroke: ReplayStroke,
  from: number,
  to: number,
): void {
  if (stroke.widths?.length) {
    // The stretch, cut where the width changes (#828): each piece is a
    // stretch of a stroke at one width, which is what the rest of this paints.
    for (const run of widthRuns(stroke.points.length, stroke.width, stroke.widths)) {
      const start = Math.max(from, run.from);
      const end = Math.min(to, run.to);
      if (run.to === run.from && from <= 0) {
        // The dot the path opened with, at a width its first segment left.
        const dot = stroke.points[run.from];
        rasterizePixelPath(pixels, CANVAS_WIDTH, CANVAS_HEIGHT, [dot, dot], run.width / 2, hexToRgba(stroke.color), false);
      } else if (end > start) {
        applyCanvasStrokeSpan(pixels, { ...stroke, width: run.width, widths: undefined }, start, end);
      }
    }
    return;
  }
  const points = stroke.points;
  const last = points.length - 1;
  if (last < 1 || to <= from) return;
  // As live playback paints (#940): the stretch as spans of the stroke's own
  // segments, each pixel decided against its whole segment, so stretches that
  // meet paint the whole stroke's pixels - a replay played to the end, or
  // scrubbed there in any steps, is the whole history's raster, and a fill
  // after it sees the same boundary. Stretches cut at interpolated points and
  // painted as segments of their own were a float's width off a diagonal.
  const start = Math.max(0, from);
  const end = Math.min(last, to);
  const spans: SegmentSpan[] = [];
  for (let index = Math.floor(start); index < end && index < last; index += 1) {
    const t0 = Math.max(0, start - index);
    const t1 = Math.min(1, end - index);
    if (t1 > t0) {
      spans.push({ a: points[index], b: points[index + 1], t0, t1 });
    }
  }
  rasterizeSpans(pixels, CANVAS_WIDTH, CANVAS_HEIGHT, spans, stroke.width / 2, hexToRgba(stroke.color));
}

/** Replay a whole history onto a blank canvas.
 *
 * Every action is applied to one scratch buffer, written back once at the end.
 * A fill-heavy turn used to round-trip the full 800x600 buffer through the GPU
 * once per fill; a replay starts from white, so it need not read back at all.
 */
export function renderCanvasActions(
  context: CanvasRenderingContext2D,
  actions: DecodedCanvasAction[],
): void {
  const imageData = context.createImageData(CANVAS_WIDTH, CANVAS_HEIGHT);
  const pixels = imageData.data;
  fillWhitePixels(pixels);
  for (const action of actions) applyCanvasAction(pixels, action);
  context.putImageData(imageData, 0, 0);
}

/**
 * Everything up to a replay position, from white: the actions before it
 * whole, and the one it sits in as far as it has got - a stroke or a
 * shape's outline part way, nothing yet for what lands whole at the end
 * of its window. What a scrub shows.
 */
export function renderCanvasActionsUpTo(
  pixels: Uint8ClampedArray,
  actions: DecodedCanvasAction[],
  position: { action: number; point: number },
): void {
  fillWhitePixels(pixels);
  for (let index = 0; index < Math.min(position.action, actions.length); index++) {
    applyCanvasAction(pixels, actions[index]);
  }
  const current = actions[position.action];
  if (!current || position.point <= 0) return;
  const stroke = replayStroke(current);
  if (stroke) applyCanvasStrokeSpan(pixels, stroke, 0, position.point);
}
