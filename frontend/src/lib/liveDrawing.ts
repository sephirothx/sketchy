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

// Path points travel either absolute (PATH_POINTS_TAG, fixed 4 bytes each) or
// delta-coded (PATH_POINTS_DELTA_TAG, first point absolute then signed-byte
// offsets). The encoder predicts both sizes and sends the smaller, per frame.
// See the matching block in `backend/app/live_drawing.py`, which this must
// agree with byte for byte.
//
// Choosing per frame matters because the delta threshold is a distance between
// consecutive samples, so it scales with the device's sample rate: ~3810 px/s
// at 120Hz, ~1905 at 60Hz, ~952 on a throttled 30Hz client. Past it escapes
// make a delta frame larger than an absolute one, on exactly the slow devices
// that most need the saving.
const DELTA_ESCAPE = -128;
const MIN_DELTA = -127;
const MAX_DELTA = 127;
const ESCAPE_RECORD_SIZE = 5;

const PATH_START_TAG = 0;
const PATH_POINTS_TAG = 1;
const PATH_END_TAG = 2;
const SHAPE_TAG = 3;
const FILL_TAG = 4;
const CLEAR_TAG = 5;
const PATH_POINTS_DELTA_TAG = 6;

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

  const fits = (index: number): boolean => {
    const deltaX = packed[index][0] - packed[index - 1][0];
    const deltaY = packed[index][1] - packed[index - 1][1];
    return deltaX >= MIN_DELTA && deltaX <= MAX_DELTA
      && deltaY >= MIN_DELTA && deltaY <= MAX_DELTA;
  };

  const absoluteSize = 1 + packed.length * 4;
  let deltaSize = 1 + 4;
  for (let index = 1; index < packed.length; index += 1) {
    deltaSize += fits(index) ? 2 : ESCAPE_RECORD_SIZE;
  }

  if (deltaSize >= absoluteSize) {
    const frame = new Uint8Array(absoluteSize);
    const absolute = new DataView(frame.buffer);
    absolute.setUint8(0, header(PATH_POINTS_TAG));
    packed.forEach(([x, y], index) => {
      absolute.setInt16(1 + index * 4, x, true);
      absolute.setInt16(3 + index * 4, y, true);
    });
    return frame;
  }

  const frame = new Uint8Array(deltaSize);
  const view = new DataView(frame.buffer);
  view.setUint8(0, header(PATH_POINTS_DELTA_TAG));
  view.setInt16(1, packed[0][0], true);
  view.setInt16(3, packed[0][1], true);
  let offset = 5;
  for (let index = 1; index < packed.length; index += 1) {
    if (fits(index)) {
      view.setInt8(offset, packed[index][0] - packed[index - 1][0]);
      view.setInt8(offset + 1, packed[index][1] - packed[index - 1][1]);
      offset += 2;
    } else {
      view.setInt8(offset, DELTA_ESCAPE);
      view.setInt16(offset + 1, packed[index][0], true);
      view.setInt16(offset + 3, packed[index][1], true);
      offset += ESCAPE_RECORD_SIZE;
    }
  }
  return frame;
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

/** Above this many payload bytes a frame goes as a binary attachment.

Socket.IO cannot carry binary inside an event without its placeholder envelope
- `51-["draw",{"_placeholder":true,"num":0}]`, 41 bytes announcing that a blob
follows, plus a second WebSocket frame for the blob itself. On a 13-byte frame
that is 76% overhead. Base64 costs a third more payload and deletes both, which
wins until the expansion overtakes the envelope it saved: measured at ~85 bytes.

Only the sender consults this. The server accepts either shape and rebroadcasts
whatever it was handed, so the threshold can move without a protocol change. */
export const MAX_BASE64_FRAME_BYTES = 85;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(text: string): Uint8Array | null {
  try {
    const binary = atob(text);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  } catch {
    return null;
  }
}

/** Put a frame in whichever shape costs least on the wire. */
export function toWireFrame(frame: number | Uint8Array): number | string | Uint8Array {
  if (typeof frame === "number") return frame;
  if (frame.byteLength > MAX_BASE64_FRAME_BYTES) return frame;
  return bytesToBase64(frame);
}

export function decodeLiveDrawing(payload: unknown): LiveDrawingPacket | null {
  if (typeof payload === "string") {
    const bytes = base64ToBytes(payload);
    if (!bytes) return null;
    return decodeLiveDrawing(bytes);
  }
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
    // Fixed-width records, so the length is its own integrity check.
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
  if (tag === PATH_POINTS_DELTA_TAG) {
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
