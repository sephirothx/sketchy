import {
  CANVAS_COORDINATE_SCALE,
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  binaryColor,
  binaryDataView,
  colorBytes,
} from "./canvasHistory.ts";
import type {
  RelativeMovePayload,
  RelativePointRecord,
  StrokeFillPayload,
  StrokeMovePayload,
  StrokePoint,
  StrokeShapePayload,
  StrokeStartPayload,
  WidthChange,
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
// -127 in the same position is a width change (#828): the new width follows
// in one byte, then the record of the point it applies from. In-band because
// a message is what costs, not a byte - see the matching block in
// `backend/app/live_drawing.py`. It takes -127 out of the delta range.
const WIDTH_MARKER = -127;
const MIN_DELTA = -126;
const MAX_DELTA = 127;
const ESCAPE_RECORD_SIZE = 5;
const WIDTH_RECORD_SIZE = 2;
// One above int16's floor: that x is the history's width marker.
const MIN_PACKED_COORDINATE = -0x7fff;
const MAX_PACKED_COORDINATE = 0x7fff;

const PATH_START_TAG = 0;
const PATH_POINTS_TAG = 1;
const PATH_END_TAG = 2;
const SHAPE_TAG = 3;
const FILL_TAG = 4;
const CLEAR_TAG = 5;
const PATH_POINTS_DELTA_TAG = 6;
const PATH_POINTS_RELATIVE_TAG = 7;
const PATH_POINTS_END_TAG = 8;

export type LiveDrawingPacket =
  | { event: "draw_start"; payload: StrokeStartPayload }
  | { event: "draw_move"; payload: StrokeMovePayload }
  // A relative frame decoded without its predecessor: offsets, not points
  // yet. `resolveRelativePoints` turns it into a `draw_move` (#559).
  | { event: "draw_move_relative"; payload: RelativeMovePayload }
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
  if (!Number.isFinite(value) || packed < MIN_PACKED_COORDINATE || packed > MAX_PACKED_COORDINATE) {
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

function stepFits(deltaX: number, deltaY: number): boolean {
  return deltaX >= MIN_DELTA && deltaX <= MAX_DELTA
    && deltaY >= MIN_DELTA && deltaY <= MAX_DELTA;
}

/** Offset records from `previous`, escaping to an absolute pair where a
step is too far for a byte. Shared by the delta frame (after its absolute
first point) and the relative frame (#559, from the open path's last point). */
function writeRecords(
  view: DataView,
  offset: number,
  packed: number[][],
  previous: number[],
  widths: Map<number, number> | null = null,
  firstIndex = 0,
): number {
  let [previousX, previousY] = previous;
  for (const [position, [x, y]] of packed.entries()) {
    const width = widths?.get(firstIndex + position);
    if (width !== undefined) {
      view.setInt8(offset, WIDTH_MARKER);
      view.setUint8(offset + 1, width);
      offset += WIDTH_RECORD_SIZE;
    }
    const deltaX = x - previousX;
    const deltaY = y - previousY;
    if (stepFits(deltaX, deltaY)) {
      view.setInt8(offset, deltaX);
      view.setInt8(offset + 1, deltaY);
      offset += 2;
    } else {
      view.setInt8(offset, DELTA_ESCAPE);
      view.setInt16(offset + 1, x, true);
      view.setInt16(offset + 3, y, true);
      offset += ESCAPE_RECORD_SIZE;
    }
    previousX = x;
    previousY = y;
  }
  return offset;
}

function recordsSize(packed: number[][], previous: number[]): number {
  let size = 0;
  let [previousX, previousY] = previous;
  for (const [x, y] of packed) {
    size += stepFits(x - previousX, y - previousY) ? 2 : ESCAPE_RECORD_SIZE;
    previousX = x;
    previousY = y;
  }
  return size;
}

/** `widths` as a lookup, validated: indices ascending and inside the batch. */
function widthChanges(widths: WidthChange[] | undefined, pointCount: number): Map<number, number> | null {
  if (!widths || widths.length === 0) return null;
  const changes = new Map<number, number>();
  let lastIndex = -1;
  for (const [index, width] of widths) {
    if (!Number.isInteger(index) || index <= lastIndex || index >= pointCount || !validWidth(width)) {
      throw new Error("Invalid width change");
    }
    changes.set(index, width);
    lastIndex = index;
  }
  return changes;
}

export function encodePathPoints(payload: StrokeMovePayload): Uint8Array {
  if (payload.points.length < 1 || payload.points.length > MAX_POINTS_PER_FRAME) {
    throw new Error("Invalid path point count");
  }
  const packed = payload.points.map((point) => [
    packedCoordinate(point.x, CANVAS_WIDTH),
    packedCoordinate(point.y, CANVAS_HEIGHT),
  ]);
  const widths = widthChanges(payload.widths, packed.length);
  const widthBytes = (widths?.size ?? 0) * WIDTH_RECORD_SIZE;

  // With the open path's last point in hand, the relative form is the
  // smallest of the three whenever its first step fits a byte: every point
  // is two bytes and there is no absolute first point (#559). A first step
  // too far would make it the largest, so the frame falls back to the
  // self-contained forms.
  if (payload.previous) {
    const previous = [
      packedCoordinate(payload.previous.x, CANVAS_WIDTH),
      packedCoordinate(payload.previous.y, CANVAS_HEIGHT),
    ];
    // An ending batch (#603) is always relative - it has an open path to
    // be relative to - escaping where a step is too far.
    // So is a batch with a width change: the change sits in front of a
    // record, and the absolute frame has none.
    if (payload.ends || widths || stepFits(packed[0][0] - previous[0], packed[0][1] - previous[1])) {
      const frame = new Uint8Array(1 + recordsSize(packed, previous) + widthBytes);
      const view = new DataView(frame.buffer);
      view.setUint8(0, header(payload.ends ? PATH_POINTS_END_TAG : PATH_POINTS_RELATIVE_TAG));
      writeRecords(view, 1, packed, previous, widths);
      return frame;
    }
  }
  if (payload.ends) throw new Error("An ending batch needs the open path's last point");
  // Without a predecessor the delta form carries the changes - but its first
  // point is not a record, so none can be on it.
  if (widths?.has(0)) throw new Error("A width change on the first point needs the open path's last point");

  const fits = (index: number): boolean =>
    stepFits(packed[index][0] - packed[index - 1][0], packed[index][1] - packed[index - 1][1]);

  const absoluteSize = 1 + packed.length * 4;
  let deltaSize = 1 + 4;
  for (let index = 1; index < packed.length; index += 1) {
    deltaSize += fits(index) ? 2 : ESCAPE_RECORD_SIZE;
  }

  if (!widths && deltaSize >= absoluteSize) {
    const frame = new Uint8Array(absoluteSize);
    const absolute = new DataView(frame.buffer);
    absolute.setUint8(0, header(PATH_POINTS_TAG));
    packed.forEach(([x, y], index) => {
      absolute.setInt16(1 + index * 4, x, true);
      absolute.setInt16(3 + index * 4, y, true);
    });
    return frame;
  }

  const frame = new Uint8Array(deltaSize + widthBytes);
  const view = new DataView(frame.buffer);
  view.setUint8(0, header(PATH_POINTS_DELTA_TAG));
  view.setInt16(1, packed[0][0], true);
  view.setInt16(3, packed[0][1], true);
  writeRecords(view, 5, packed.slice(1), packed[0], widths, 1);
  return frame;
}

function inPackedRange(x: number, y: number): boolean {
  return x >= MIN_PACKED_COORDINATE && x <= MAX_PACKED_COORDINATE
    && y >= MIN_PACKED_COORDINATE && y <= MAX_PACKED_COORDINATE;
}

/** Walk offset records to the end of the frame. Variable-length, so every
step is bounded by the frame it reads. A width change must be followed, in
this frame, by the record of the point it applies from: one that trails the
frame or sits beside another is refused. Null for a malformed frame. */
function readRecords(
  view: DataView,
  offset: number,
  firstIndex: number,
): { records: RelativePointRecord[]; widths: WidthChange[] } | null {
  const records: RelativePointRecord[] = [];
  const widths: WidthChange[] = [];
  let widthPending = false;
  while (offset < view.byteLength) {
    const lead = view.getInt8(offset);
    if (lead === WIDTH_MARKER) {
      if (widthPending || offset + WIDTH_RECORD_SIZE > view.byteLength) return null;
      const width = view.getUint8(offset + 1);
      if (!validWidth(width)) return null;
      widths.push([firstIndex + records.length, width]);
      widthPending = true;
      offset += WIDTH_RECORD_SIZE;
      continue;
    }
    if (lead === DELTA_ESCAPE) {
      if (offset + ESCAPE_RECORD_SIZE > view.byteLength) return null;
      const x = view.getInt16(offset + 1, true);
      const y = view.getInt16(offset + 3, true);
      if (!inPackedRange(x, y)) return null;
      records.push({ x, y });
      offset += ESCAPE_RECORD_SIZE;
    } else {
      if (offset + 2 > view.byteLength) return null;
      records.push({ dx: lead, dy: view.getInt8(offset + 1) });
      offset += 2;
    }
    widthPending = false;
    if (firstIndex + records.length > MAX_POINTS_PER_FRAME) return null;
  }
  return widthPending ? null : { records, widths };
}

/** The points a relative frame stands for, given the open path's last point.
Null when a step walks a coordinate out of the packed range. */
export function resolveRelativePoints(
  packet: Extract<LiveDrawingPacket, { event: "draw_move_relative" }>,
  previous: StrokePoint,
): Extract<LiveDrawingPacket, { event: "draw_move" }> | null {
  let x = packedCoordinate(previous.x, CANVAS_WIDTH);
  let y = packedCoordinate(previous.y, CANVAS_HEIGHT);
  const points: StrokePoint[] = [];
  for (const record of packet.payload.records) {
    if ("dx" in record) {
      x += record.dx;
      y += record.dy;
      if (!inPackedRange(x, y)) return null;
    } else {
      x = record.x;
      y = record.y;
    }
    points.push({
      x: unpackedCoordinate(x, CANVAS_WIDTH),
      y: unpackedCoordinate(y, CANVAS_HEIGHT),
    });
  }
  const payload: StrokeMovePayload = { points };
  if (packet.payload.widths) payload.widths = packet.payload.widths;
  if (packet.payload.ends) payload.ends = true;
  return { event: "draw_move", payload };
}

/** Whether this frame closes the open path: `draw_end`, or a final batch (#603). */
export function endsPath(packet: LiveDrawingPacket): boolean {
  return packet.event === "draw_end"
    || ((packet.event === "draw_move" || packet.event === "draw_move_relative") && packet.payload.ends === true);
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
/** A frame as the client holds it: a bare header byte for the two control
actions, or the encoded bytes of a data-bearing one. */
export type DrawingFrame = number | Uint8Array;

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

/** Decode a frame. A relative `draw_move` (#559) needs the open path's last
point to become points; given `previous` it comes back as an ordinary
`draw_move`, without it as `draw_move_relative` for the caller to resolve. */
export function decodeLiveDrawing(
  payload: unknown,
  previous?: StrokePoint | null,
): LiveDrawingPacket | null {
  if (typeof payload === "string") {
    const bytes = base64ToBytes(payload);
    if (!bytes) return null;
    return decodeLiveDrawing(bytes, previous);
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
    if (!inPackedRange(view.getInt16(5, true), view.getInt16(7, true))) return null;
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
      // int16's floor is the history's width marker, not a coordinate.
      if (!inPackedRange(view.getInt16(offset, true), view.getInt16(offset + 2, true))) return null;
      points.push({
        x: unpackedCoordinate(view.getInt16(offset, true), CANVAS_WIDTH),
        y: unpackedCoordinate(view.getInt16(offset + 2, true), CANVAS_HEIGHT),
      });
    }
    return { event: "draw_move", payload: { points } };
  }
  if (tag === PATH_POINTS_DELTA_TAG) {
    if (view.byteLength < 5) return null;
    const first = { x: view.getInt16(1, true), y: view.getInt16(3, true) };
    if (!inPackedRange(first.x, first.y)) return null;
    const read = readRecords(view, 5, 1);
    if (!read) return null;
    // The rest are offsets from the first point, which is what a relative
    // frame's are from its predecessor: one walk serves both.
    const rest = resolveRelativePoints(
      { event: "draw_move_relative", payload: { records: read.records } },
      { x: unpackedCoordinate(first.x, CANVAS_WIDTH), y: unpackedCoordinate(first.y, CANVAS_HEIGHT) },
    );
    if (!rest) return null;
    const points = [
      { x: unpackedCoordinate(first.x, CANVAS_WIDTH), y: unpackedCoordinate(first.y, CANVAS_HEIGHT) },
      ...rest.payload.points,
    ];
    return { event: "draw_move", payload: read.widths.length > 0 ? { points, widths: read.widths } : { points } };
  }
  if (tag === PATH_POINTS_RELATIVE_TAG || tag === PATH_POINTS_END_TAG) {
    const read = readRecords(view, 1, 0);
    if (!read || read.records.length === 0) return null;
    const payload: RelativeMovePayload = { records: read.records };
    if (read.widths.length > 0) payload.widths = read.widths;
    if (tag === PATH_POINTS_END_TAG) payload.ends = true;
    const relative = { event: "draw_move_relative" as const, payload };
    return previous ? resolveRelativePoints(relative, previous) : relative;
  }
  if (tag === PATH_END_TAG) {
    return view.byteLength === 1 ? { event: "draw_end", payload: {} } : null;
  }
  if (tag === SHAPE_TAG) {
    if (view.byteLength !== 14) return null;
    const shape = SHAPES[view.getUint8(1)];
    const width = view.getUint8(5);
    if (!shape || !validWidth(width)) return null;
    if (
      !inPackedRange(view.getInt16(6, true), view.getInt16(8, true))
      || !inPackedRange(view.getInt16(10, true), view.getInt16(12, true))
    ) return null;
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
        // The centre of the pixel, not its corner - see the matching comment
        // in `backend/app/live_drawing.py`. `x / CANVAS_WIDTH` does not
        // survive being re-quantized by the renderer: 37 columns and 26 rows
        // land a pixel short, and for a flood fill one pixel can be the far
        // side of an outline.
        x: (x + 0.5) / CANVAS_WIDTH,
        y: (y + 0.5) / CANVAS_HEIGHT,
      },
    };
  }
  if (tag === CLEAR_TAG) {
    return view.byteLength === 1 ? { event: "clear_canvas", payload: {} } : null;
  }
  return null;
}
