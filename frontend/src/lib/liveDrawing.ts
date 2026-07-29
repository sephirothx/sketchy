import {
  CANVAS_COORDINATE_SCALE,
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
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

function dataView(payload: unknown): DataView | null {
  if (payload instanceof ArrayBuffer) return new DataView(payload);
  if (ArrayBuffer.isView(payload)) {
    return new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  }
  return null;
}

function colorBytes(color: string): [number, number, number] {
  if (!/^#[0-9a-fA-F]{6}$/.test(color)) throw new Error("Invalid drawing color");
  const value = Number.parseInt(color.slice(1), 16);
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}

function readColor(view: DataView, offset: number): string {
  const value = (
    view.getUint8(offset) * 0x10000
    + view.getUint8(offset + 1) * 0x100
    + view.getUint8(offset + 2)
  );
  return `#${value.toString(16).padStart(6, "0")}`;
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

function writeColor(view: DataView, offset: number, color: string): void {
  const bytes = colorBytes(color);
  bytes.forEach((byte, index) => view.setUint8(offset + index, byte));
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
  const frame = new Uint8Array(1 + payload.points.length * 4);
  const view = new DataView(frame.buffer);
  view.setUint8(0, header(PATH_POINTS_TAG));
  payload.points.forEach((point, index) => {
    const offset = 1 + index * 4;
    view.setInt16(offset, packedCoordinate(point.x, CANVAS_WIDTH), true);
    view.setInt16(offset + 2, packedCoordinate(point.y, CANVAS_HEIGHT), true);
  });
  return frame;
}

export function encodePathEnd(): Uint8Array {
  return Uint8Array.of(header(PATH_END_TAG));
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

export function encodeClear(): Uint8Array {
  return Uint8Array.of(header(CLEAR_TAG));
}

export function decodeLiveDrawing(payload: unknown): LiveDrawingPacket | null {
  const view = dataView(payload);
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
        color: readColor(view, 1),
        width,
        x: unpackedCoordinate(view.getInt16(5, true), CANVAS_WIDTH),
        y: unpackedCoordinate(view.getInt16(7, true), CANVAS_HEIGHT),
      },
    };
  }
  if (tag === PATH_POINTS_TAG) {
    if (
      view.byteLength <= 1
      || (view.byteLength - 1) % 4 !== 0
      || (view.byteLength - 1) / 4 > MAX_POINTS_PER_FRAME
    ) {
      return null;
    }
    const points = [];
    for (let offset = 1; offset < view.byteLength; offset += 4) {
      points.push({
        x: unpackedCoordinate(view.getInt16(offset, true), CANVAS_WIDTH),
        y: unpackedCoordinate(view.getInt16(offset + 2, true), CANVAS_HEIGHT),
      });
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
        color: readColor(view, 2),
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
        color: readColor(view, 1),
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
