import type {
  CanvasSyncPayload,
  ShapeType,
  StrokeShapePayload,
} from "../types";
import type { LiveDrawingPacket } from "./liveDrawing";

export const CANVAS_WIDTH = 800;
export const CANVAS_HEIGHT = 600;
export const CANVAS_COORDINATE_SCALE = 4;

const CANVAS_HISTORY_VERSION = 1;
const MAX_BRUSH_WIDTH = 64;
const MAX_NORMALIZED_COORDINATE_MAGNITUDE = 1_000_000;
const MAX_CANVAS_ACTIONS = 20_000;
const MAX_CANVAS_POINTS = 25_000;
const HISTORY_SHAPES: ShapeType[] = ["rectangle", "ellipse", "triangle"];
const BINARY_HISTORY_MAGIC = [0x53, 0x4b, 0x43, 0x48]; // "SKCH"
const BINARY_HEADER_SIZE = 7;
const BINARY_OFFSET_SIZE = 4;
const PATH_HEADER_SIZE = 5;
const PATH_POINT_SIZE = 4;
const SHAPE_ACTION_SIZE = 14;
const FILL_ACTION_SIZE = 8;
const CLEAR_ACTION_SIZE = 1;

interface CanvasPoint {
  x: number;
  y: number;
}

export type DecodedCanvasAction =
  | { kind: "path"; color: string; width: number; points: CanvasPoint[] }
  | { kind: "shape"; payload: StrokeShapePayload }
  | { kind: "fill"; color: string; x: number; y: number }
  | { kind: "clear" };

export type CanvasUndoPayload = [fromRevision: number, toRevision: number];

function isRevision(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

/**
 * Semantic drawing history mirrored from the authoritative server history.
 *
 * Live Socket.IO drawing events are ordered, so clients can advance the same
 * revision locally without adding metadata to every drawing packet. Full sync
 * seeds the revision on join/reconnect; Undo verifies it before mutating.
 */
export class ClientCanvasHistory {
  actions: DecodedCanvasAction[] = [];
  revision: number | null = null;
  private activePath: Extract<DecodedCanvasAction, { kind: "path" }> | null = null;

  replace(actions: DecodedCanvasAction[], revision: unknown): boolean {
    if (!isRevision(revision)) return false;
    this.actions = actions;
    this.revision = revision;
    this.activePath = null;
    return true;
  }

  reset(revision: unknown): boolean {
    if (!isRevision(revision)) return false;
    this.actions = [];
    this.revision = revision;
    this.activePath = null;
    return true;
  }

  apply(packet: LiveDrawingPacket): boolean {
    if (packet.event === "draw_move") {
      if (!this.activePath && this.actions.at(-1)?.kind === "path") {
        this.activePath = this.actions.at(-1) as Extract<
          DecodedCanvasAction,
          { kind: "path" }
        >;
      }
      if (!this.activePath) return false;
      this.activePath.points.push(
        ...packet.payload.points.map((point) => ({
          x: point.x * CANVAS_WIDTH,
          y: point.y * CANVAS_HEIGHT,
        })),
      );
      return true;
    }
    if (packet.event === "draw_end") {
      if (!this.activePath && this.actions.at(-1)?.kind === "path") {
        this.activePath = this.actions.at(-1) as Extract<
          DecodedCanvasAction,
          { kind: "path" }
        >;
      }
      if (!this.activePath) return false;
      this.activePath = null;
      return true;
    }
    if (packet.event === "clear_canvas") {
      if (this.actions.length === 0 || this.actions.at(-1)?.kind === "clear") {
        return false;
      }
      this.actions.push({ kind: "clear" });
      this.activePath = null;
      this.advanceRevision();
      return true;
    }

    // Starting a new action after Clear permanently discards the pre-clear
    // history, matching Game.record_stroke on the server.
    if (this.actions.at(-1)?.kind === "clear") this.actions = [];
    this.activePath = null;

    if (packet.event === "draw_start") {
      const action: Extract<DecodedCanvasAction, { kind: "path" }> = {
        kind: "path",
        color: packet.payload.color,
        width: packet.payload.width,
        points: [{
          x: packet.payload.x * CANVAS_WIDTH,
          y: packet.payload.y * CANVAS_HEIGHT,
        }],
      };
      this.actions.push(action);
      this.activePath = action;
    } else if (packet.event === "draw_shape") {
      this.actions.push({
        kind: "shape",
        payload: {
          ...packet.payload,
          from: { ...packet.payload.from },
          to: { ...packet.payload.to },
        },
      });
    } else {
      this.actions.push({
        kind: "fill",
        color: packet.payload.color,
        x: Math.min(CANVAS_WIDTH - 1, Math.floor(packet.payload.x * CANVAS_WIDTH)),
        y: Math.min(CANVAS_HEIGHT - 1, Math.floor(packet.payload.y * CANVAS_HEIGHT)),
      });
    }
    this.advanceRevision();
    return true;
  }

  undo(payload: unknown): boolean {
    if (
      !Array.isArray(payload)
      || payload.length !== 2
      || !isRevision(payload[0])
      || !isRevision(payload[1])
      || payload[1] !== payload[0] + 1
      || this.revision !== payload[0]
      || this.actions.length === 0
    ) {
      return false;
    }
    this.actions.pop();
    this.activePath = null;
    this.revision = payload[1];
    return true;
  }

  private advanceRevision(): void {
    if (this.revision !== null) this.revision += 1;
  }
}

function isNumberBetween(value: unknown, low: number, high: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= low && value <= high;
}

function isIntegerBetween(value: unknown, low: number, high: number): value is number {
  return Number.isInteger(value) && isNumberBetween(value, low, high);
}

function historyColor(value: unknown): string | null {
  if (!isIntegerBetween(value, 0, 0xffffff)) return null;
  return `#${value.toString(16).padStart(6, "0")}`;
}

function decodeJsonCanvasHistory(payload: unknown): DecodedCanvasAction[] | null {
  if (
    typeof payload !== "object"
    || payload === null
    || Array.isArray(payload)
    || Object.keys(payload).length !== 2
    || !Object.hasOwn(payload, "v")
    || !Object.hasOwn(payload, "a")
    || (payload as CanvasSyncPayload).v !== CANVAS_HISTORY_VERSION
    || !Array.isArray((payload as CanvasSyncPayload).a)
    || (payload as CanvasSyncPayload).a.length > MAX_CANVAS_ACTIONS
  ) {
    return null;
  }

  const decoded: DecodedCanvasAction[] = [];
  let totalPoints = 0;
  for (const rawAction of (payload as CanvasSyncPayload).a) {
    if (!Array.isArray(rawAction) || !isIntegerBetween(rawAction[0], 0, 3)) return null;
    const tag = rawAction[0];
    if (tag === 0) {
      const color = historyColor(rawAction[1]);
      if (
        rawAction.length < 5
        || (rawAction.length - 3) % 2 !== 0
        || (rawAction.length - 3) / 2 > MAX_CANVAS_POINTS
        || color === null
        || !isIntegerBetween(rawAction[2], 1, MAX_BRUSH_WIDTH)
      ) {
        return null;
      }
      const points: CanvasPoint[] = [];
      for (let index = 3; index < rawAction.length; index += 2) {
        if (
          !isNumberBetween(
            rawAction[index],
            -MAX_NORMALIZED_COORDINATE_MAGNITUDE,
            MAX_NORMALIZED_COORDINATE_MAGNITUDE,
          )
          || !isNumberBetween(
            rawAction[index + 1],
            -MAX_NORMALIZED_COORDINATE_MAGNITUDE,
            MAX_NORMALIZED_COORDINATE_MAGNITUDE,
          )
        ) {
          return null;
        }
        points.push({
          x: rawAction[index] * CANVAS_WIDTH,
          y: rawAction[index + 1] * CANVAS_HEIGHT,
        });
      }
      totalPoints += points.length;
      if (totalPoints > MAX_CANVAS_POINTS) return null;
      decoded.push({ kind: "path", color, width: rawAction[2], points });
    } else if (tag === 1) {
      const shapeId = rawAction[1];
      const color = historyColor(rawAction[2]);
      if (
        rawAction.length !== 8
        || !isIntegerBetween(shapeId, 0, HISTORY_SHAPES.length - 1)
        || color === null
        || !isIntegerBetween(rawAction[3], 1, MAX_BRUSH_WIDTH)
        || rawAction.slice(4).some(
          (value) => !isNumberBetween(
            value,
            -MAX_NORMALIZED_COORDINATE_MAGNITUDE,
            MAX_NORMALIZED_COORDINATE_MAGNITUDE,
          ),
        )
      ) {
        return null;
      }
      decoded.push({
        kind: "shape",
        payload: {
          shape: HISTORY_SHAPES[shapeId],
          color,
          width: rawAction[3],
          from: { x: rawAction[4], y: rawAction[5] },
          to: { x: rawAction[6], y: rawAction[7] },
        },
      });
    } else if (tag === 2) {
      const color = historyColor(rawAction[1]);
      if (
        rawAction.length !== 4
        || color === null
        || !isIntegerBetween(rawAction[2], 0, CANVAS_WIDTH - 1)
        || !isIntegerBetween(rawAction[3], 0, CANVAS_HEIGHT - 1)
      ) {
        return null;
      }
      decoded.push({ kind: "fill", color, x: rawAction[2], y: rawAction[3] });
    } else {
      if (rawAction.length !== 1) return null;
      decoded.push({ kind: "clear" });
    }
  }
  return decoded;
}

function binaryDataView(payload: unknown): DataView | null {
  if (payload instanceof ArrayBuffer) return new DataView(payload);
  if (ArrayBuffer.isView(payload)) {
    return new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  }
  return null;
}

function binaryColor(view: DataView, offset: number): string {
  const color = (
    view.getUint8(offset) * 0x10000
    + view.getUint8(offset + 1) * 0x100
    + view.getUint8(offset + 2)
  );
  return `#${color.toString(16).padStart(6, "0")}`;
}

function decodeBinaryCanvasHistory(view: DataView): DecodedCanvasAction[] | null {
  if (view.byteLength < BINARY_HEADER_SIZE + BINARY_OFFSET_SIZE) return null;
  if (
    BINARY_HISTORY_MAGIC.some(
      (byte, index) => view.getUint8(index) !== byte,
    )
    || view.getUint8(4) !== CANVAS_HISTORY_VERSION
  ) {
    return null;
  }

  const actionCount = view.getUint16(5, true);
  if (actionCount > MAX_CANVAS_ACTIONS) return null;
  const dataStart = (
    BINARY_HEADER_SIZE
    + (actionCount + 1) * BINARY_OFFSET_SIZE
  );
  if (dataStart > view.byteLength) return null;

  const offsets: number[] = [];
  for (let index = 0; index <= actionCount; index++) {
    offsets.push(
      view.getUint32(
        BINARY_HEADER_SIZE + index * BINARY_OFFSET_SIZE,
        true,
      ),
    );
  }
  const dataLength = view.byteLength - dataStart;
  if (offsets[0] !== 0 || offsets[actionCount] !== dataLength) return null;
  for (let index = 0; index < actionCount; index++) {
    if (offsets[index] >= offsets[index + 1]) return null;
  }

  const decoded: DecodedCanvasAction[] = [];
  let totalPoints = 0;
  for (let index = 0; index < actionCount; index++) {
    const start = dataStart + offsets[index];
    const end = dataStart + offsets[index + 1];
    const recordLength = end - start;
    const tag = view.getUint8(start);
    if (tag === 0) {
      if (
        recordLength < PATH_HEADER_SIZE + PATH_POINT_SIZE
        || (recordLength - PATH_HEADER_SIZE) % PATH_POINT_SIZE !== 0
      ) {
        return null;
      }
      const width = view.getUint8(start + 4);
      if (!isIntegerBetween(width, 1, MAX_BRUSH_WIDTH)) return null;
      const points: CanvasPoint[] = [];
      for (
        let offset = start + PATH_HEADER_SIZE;
        offset < end;
        offset += PATH_POINT_SIZE
      ) {
        points.push({
          x: view.getInt16(offset, true) / CANVAS_COORDINATE_SCALE,
          y: view.getInt16(offset + 2, true) / CANVAS_COORDINATE_SCALE,
        });
      }
      totalPoints += points.length;
      if (totalPoints > MAX_CANVAS_POINTS) return null;
      decoded.push({
        kind: "path",
        color: binaryColor(view, start + 1),
        width,
        points,
      });
    } else if (tag === 1) {
      if (recordLength !== SHAPE_ACTION_SIZE) return null;
      const shapeId = view.getUint8(start + 1);
      const width = view.getUint8(start + 5);
      if (
        !isIntegerBetween(shapeId, 0, HISTORY_SHAPES.length - 1)
        || !isIntegerBetween(width, 1, MAX_BRUSH_WIDTH)
      ) {
        return null;
      }
      decoded.push({
        kind: "shape",
        payload: {
          shape: HISTORY_SHAPES[shapeId],
          color: binaryColor(view, start + 2),
          width,
          from: {
            x: view.getInt16(start + 6, true)
              / (CANVAS_WIDTH * CANVAS_COORDINATE_SCALE),
            y: view.getInt16(start + 8, true)
              / (CANVAS_HEIGHT * CANVAS_COORDINATE_SCALE),
          },
          to: {
            x: view.getInt16(start + 10, true)
              / (CANVAS_WIDTH * CANVAS_COORDINATE_SCALE),
            y: view.getInt16(start + 12, true)
              / (CANVAS_HEIGHT * CANVAS_COORDINATE_SCALE),
          },
        },
      });
    } else if (tag === 2) {
      if (recordLength !== FILL_ACTION_SIZE) return null;
      const x = view.getUint16(start + 4, true);
      const y = view.getUint16(start + 6, true);
      if (x >= CANVAS_WIDTH || y >= CANVAS_HEIGHT) return null;
      decoded.push({
        kind: "fill",
        color: binaryColor(view, start + 1),
        x,
        y,
      });
    } else if (tag === 3) {
      if (recordLength !== CLEAR_ACTION_SIZE) return null;
      decoded.push({ kind: "clear" });
    } else {
      return null;
    }
  }
  return decoded;
}

export function decodeCanvasHistory(payload: unknown): DecodedCanvasAction[] | null {
  const binary = binaryDataView(payload);
  return binary
    ? decodeBinaryCanvasHistory(binary)
    : decodeJsonCanvasHistory(payload);
}
