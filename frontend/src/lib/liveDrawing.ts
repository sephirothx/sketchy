import {
  CANVAS_COORDINATE_SCALE,
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  binaryColor,
  binaryDataView,
  colorBytes,
} from "./canvasHistory.ts";
import type {
  StrokeFillPayload,
  StrokeMovePayload,
  StrokeShapePayload,
  StrokeStartPayload,
} from "../types.ts";

const LIVE_DRAWING_VERSION = 1;
const MAX_BRUSH_WIDTH = 64;
const MAX_POINTS_PER_FRAME = 256;
const SHAPES = ["rectangle", "ellipse", "triangle"] as const;

// Path points travel as deltas from the point before them; see the matching
// block in `backend/app/live_drawing.py`, which this must agree with byte for
// byte. The first point of every frame stays absolute so each frame decodes
// independently of the ones around it. -128 is not a delta but the escape
// marker: a stroke moving faster than ~3810 px/s (measured crossover at a
// 120Hz pointer) writes it, followed by an absolute pair.
const DELTA_ESCAPE = -128;
const MIN_DELTA = -127;
const MAX_DELTA = 127;

const PATH_START_TAG = 0;
const PATH_POINTS_TAG = 1;
const PATH_END_TAG = 2;
const SHAPE_TAG = 3;
const FILL_TAG = 4;
const CLEAR_TAG = 5;

export type LiveDrawingPacket =
  | { event: "draw_start"; payload: StrokeStartPayload }
  | { event: "draw_move"; payload: StrokeMovePayload }
  | { event: "draw_end"; payload: Record<string, never> }
  | { event: "draw_shape"; payload: StrokeShapePayload }
  | { event: "draw_fill"; payload: StrokeFillPayload }
  | { event: "clear_canvas"; payload: Record<string, never> };

function header(tag: number): number {
  return (LIVE_DRAWING_VERSION << 4) | tag;
}

function writeColor(view: DataView, offset: number, color: string): void {
  const bytes = colorBytes(color);
  bytes.forEach((byte, index) => view.setUint8(offset + index, byte));
}

function packedCoordinate(value: number, canvasSize: number): number {
  const packed = Math.round(value * canvasSize * CANVAS_COORDINATE_SCALE);
  if (!Number.isFinite(value) || packed < -0x8000 || packed > 0x7fff) {
    throw new Error("Drawing coordinate is outside packed range");
  }
  return packed;
}

function unpackedCoordinate(value: number, canvasSize: number): number {
  return value / (canvasSize * CANVAS_COORDINATE_SCALE);
}

function validWidth(width: number): boolean {
  return Number.isInteger(width) && width >= 1 && width <= MAX_BRUSH_WIDTH;
}

export function encodePathStart(payload: StrokeStartPayload): Uint8Array {
  if (!validWidth(payload.width)) throw new Error("Invalid brush width");
  const frame = new Uint8Array(9);
  const view = new DataView(frame.buffer);
  view.setUint8(0, header(PATH_START_TAG));
  writeColor(view, 1, payload.color);
  view.setUint8(4, payload.width);
  view.setInt16(5, packedCoordinate(payload.x, CANVAS_WIDTH), true);
  view.setInt16(7, packedCoordinate(payload.y, CANVAS_HEIGHT), true);
  return frame;
}

export function encodePathPoints(payload: StrokeMovePayload): Uint8Array {
  if (payload.points.length < 1 || payload.points.length > MAX_POINTS_PER_FRAME) {
    throw new Error("Invalid path point count");
  }
  const packed = payload.points.map((point) => [
    packedCoordinate(point.x, CANVAS_WIDTH),
    packedCoordinate(point.y, CANVAS_HEIGHT),
  ]);
  // Worst case is every point escaping, which is still bounded.
  const scratch = new Uint8Array(1 + packed.length * (1 + 4));
  const view = new DataView(scratch.buffer);
  view.setUint8(0, header(PATH_POINTS_TAG));
  view.setInt16(1, packed[0][0], true);
  view.setInt16(3, packed[0][1], true);
  let offset = 5;
  for (let index = 1; index < packed.length; index += 1) {
    const deltaX = packed[index][0] - packed[index - 1][0];
    const deltaY = packed[index][1] - packed[index - 1][1];
    if (
      deltaX >= MIN_DELTA && deltaX <= MAX_DELTA
      && deltaY >= MIN_DELTA && deltaY <= MAX_DELTA
    ) {
      view.setInt8(offset, deltaX);
      view.setInt8(offset + 1, deltaY);
      offset += 2;
    } else {
      view.setInt8(offset, DELTA_ESCAPE);
      view.setInt16(offset + 1, packed[index][0], true);
      view.setInt16(offset + 3, packed[index][1], true);
      offset += 5;
    }
  }
  return scratch.slice(0, offset);
}

export function encodePathEnd(): number {
  return header(PATH_END_TAG);
}

export function encodeShape(payload: StrokeShapePayload): Uint8Array {
  const shapeId = SHAPES.indexOf(payload.shape);
  if (shapeId < 0 || !validWidth(payload.width)) throw new Error("Invalid shape action");
  const frame = new Uint8Array(14);
  const view = new DataView(frame.buffer);
  view.setUint8(0, header(SHAPE_TAG));
  view.setUint8(1, shapeId);
  writeColor(view, 2, payload.color);
  view.setUint8(5, payload.width);
  view.setInt16(6, packedCoordinate(payload.from.x, CANVAS_WIDTH), true);
  view.setInt16(8, packedCoordinate(payload.from.y, CANVAS_HEIGHT), true);
  view.setInt16(10, packedCoordinate(payload.to.x, CANVAS_WIDTH), true);
  view.setInt16(12, packedCoordinate(payload.to.y, CANVAS_HEIGHT), true);
  return frame;
}

export function encodeFill(payload: StrokeFillPayload): Uint8Array {
  if (
    !Number.isFinite(payload.x)
    || !Number.isFinite(payload.y)
    || payload.x < 0
    || payload.x >= 1
    || payload.y < 0
    || payload.y >= 1
  ) {
    throw new Error("Invalid fill point");
  }
  const frame = new Uint8Array(8);
  const view = new DataView(frame.buffer);
  view.setUint8(0, header(FILL_TAG));
  writeColor(view, 1, payload.color);
  view.setUint16(4, Math.min(CANVAS_WIDTH - 1, Math.trunc(payload.x * CANVAS_WIDTH)), true);
  view.setUint16(6, Math.min(CANVAS_HEIGHT - 1, Math.trunc(payload.y * CANVAS_HEIGHT)), true);
  return frame;
}

export function encodeClear(): number {
  return header(CLEAR_TAG);
}

export function decodeLiveDrawing(payload: unknown): LiveDrawingPacket | null {
  if (typeof payload === "number") {
    if (
      !Number.isInteger(payload)
      || payload < 0
      || payload > 0xff
      || payload >> 4 !== LIVE_DRAWING_VERSION
    ) {
      return null;
    }
    const controlTag = payload & 0x0f;
    if (controlTag === PATH_END_TAG) return { event: "draw_end", payload: {} };
    if (controlTag === CLEAR_TAG) return { event: "clear_canvas", payload: {} };
    return null;
  }
  const view = binaryDataView(payload);
  if (!view || view.byteLength < 1 || view.getUint8(0) >> 4 !== LIVE_DRAWING_VERSION) {
    return null;
  }
  const tag = view.getUint8(0) & 0x0f;
  if (tag === PATH_START_TAG) {
    const width = view.byteLength === 9 ? view.getUint8(4) : 0;
    if (!validWidth(width)) return null;
    return {
      event: "draw_start",
      payload: {
        color: binaryColor(view, 1),
        width,
        x: unpackedCoordinate(view.getInt16(5, true), CANVAS_WIDTH),
        y: unpackedCoordinate(view.getInt16(7, true), CANVAS_HEIGHT),
      },
    };
  }
  if (tag === PATH_POINTS_TAG) {
    // Variable-length records, so the frame is walked rather than divided.
    if (view.byteLength < 5) return null;
    let x = view.getInt16(1, true);
    let y = view.getInt16(3, true);
    let offset = 5;
    const points = [{
      x: unpackedCoordinate(x, CANVAS_WIDTH),
      y: unpackedCoordinate(y, CANVAS_HEIGHT),
    }];
    while (offset < view.byteLength) {
      if (view.getInt8(offset) === DELTA_ESCAPE) {
        if (offset + 5 > view.byteLength) return null;
        x = view.getInt16(offset + 1, true);
        y = view.getInt16(offset + 3, true);
        offset += 5;
      } else {
        if (offset + 2 > view.byteLength) return null;
        x += view.getInt8(offset);
        y += view.getInt8(offset + 1);
        offset += 2;
        if (x < -0x8000 || x > 0x7fff || y < -0x8000 || y > 0x7fff) return null;
      }
      points.push({
        x: unpackedCoordinate(x, CANVAS_WIDTH),
        y: unpackedCoordinate(y, CANVAS_HEIGHT),
      });
      if (points.length > MAX_POINTS_PER_FRAME) return null;
    }
    return { event: "draw_move", payload: { points } };
  }
  if (tag === PATH_END_TAG) {
    return view.byteLength === 1 ? { event: "draw_end", payload: {} } : null;
  }
  if (tag === SHAPE_TAG) {
    if (view.byteLength !== 14) return null;
    const shape = SHAPES[view.getUint8(1)];
    const width = view.getUint8(5);
    if (!shape || !validWidth(width)) return null;
    return {
      event: "draw_shape",
      payload: {
        shape,
        color: binaryColor(view, 2),
        width,
        from: {
          x: unpackedCoordinate(view.getInt16(6, true), CANVAS_WIDTH),
          y: unpackedCoordinate(view.getInt16(8, true), CANVAS_HEIGHT),
        },
        to: {
          x: unpackedCoordinate(view.getInt16(10, true), CANVAS_WIDTH),
          y: unpackedCoordinate(view.getInt16(12, true), CANVAS_HEIGHT),
        },
      },
    };
  }
  if (tag === FILL_TAG) {
    if (view.byteLength !== 8) return null;
    const x = view.getUint16(4, true);
    const y = view.getUint16(6, true);
    if (x >= CANVAS_WIDTH || y >= CANVAS_HEIGHT) return null;
    return {
      event: "draw_fill",
      payload: {
        color: binaryColor(view, 1),
        x: x / CANVAS_WIDTH,
        y: y / CANVAS_HEIGHT,
      },
    };
  }
  if (tag === CLEAR_TAG) {
    return view.byteLength === 1 ? { event: "clear_canvas", payload: {} } : null;
  }
  return null;
}
