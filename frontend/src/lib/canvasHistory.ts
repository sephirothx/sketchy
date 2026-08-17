import type {
  CanvasSyncPayload,
  ShapeType,
  StrokeShapePayload,
} from "../types";
import type { LiveDrawingPacket } from "./liveDrawing";

export const CANVAS_WIDTH = 800;
export const CANVAS_HEIGHT = 600;
export const CANVAS_COORDINATE_SCALE = 4;

function envCap(name: string, fallback: number): number {
  const value = (globalThis as Record<string, unknown>)[name];
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}

export const PATH_WORK = 1;
export const SHAPE_WORK = 1;
export const FILL_WORK = 200;
export const CLEAR_WORK = 0;
export const CHECKPOINT_WORK = 0;
export const MAX_WINDOW_WORK = envCap("SKETCHY_MAX_WINDOW_WORK", 10_000);
export const MAX_WINDOW_ACTIONS = envCap("SKETCHY_MAX_WINDOW_ACTIONS", 256);
export const MAX_CANVAS_POINTS = 25_000;
export const MAX_CHECKPOINT_PNG = 400_000;
export const MAX_SYNC_BYTES = 524_288;

const CANVAS_HISTORY_VERSION = 2;
const MAX_BRUSH_WIDTH = 64;
const MAX_NORMALIZED_COORDINATE_MAGNITUDE = 1_000_000;
const MAX_CANVAS_ACTIONS = MAX_WINDOW_ACTIONS + 1;
const HISTORY_SHAPES: ShapeType[] = ["rectangle", "ellipse", "triangle"];
const BINARY_HISTORY_MAGIC = [0x53, 0x4b, 0x43, 0x48]; // "SKCH"
const BINARY_HEADER_SIZE = 7;
const BINARY_OFFSET_SIZE = 4;
const PATH_HEADER_SIZE = 5;
const PATH_POINT_SIZE = 4;
const SHAPE_ACTION_SIZE = 14;
const FILL_ACTION_SIZE = 8;
const CLEAR_ACTION_SIZE = 1;
const CHECKPOINT_HEADER_SIZE = 5;
const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

interface CanvasPoint {
  x: number;
  y: number;
}

export type DecodedCanvasAction =
  | { kind: "path"; color: string; width: number; points: CanvasPoint[] }
  | { kind: "shape"; payload: StrokeShapePayload }
  | { kind: "fill"; color: string; x: number; y: number }
  | { kind: "clear" }
  | { kind: "checkpoint"; png: Uint8Array };

const CRC32_TABLE = new Uint32Array(256);
for (let index = 0; index < CRC32_TABLE.length; index++) {
  let value = index;
  for (let bit = 0; bit < 8; bit++) {
    value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  CRC32_TABLE[index] = value >>> 0;
}

function crc32(bytes: Uint8Array, previous = 0): number {
  let value = (previous ^ 0xffffffff) >>> 0;
  for (const byte of bytes) {
    value = CRC32_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
  }
  return (value ^ 0xffffffff) >>> 0;
}

export function colorBytes(color: string): [number, number, number] {
  const value = Number.parseInt(color.slice(1), 16);
  return [(value >>> 16) & 0xff, (value >>> 8) & 0xff, value & 0xff];
}

function canonicalActionBytes(action: DecodedCanvasAction): Uint8Array {
  if (action.kind === "path") {
    const bytes = new Uint8Array(PATH_HEADER_SIZE + action.points.length * PATH_POINT_SIZE);
    const view = new DataView(bytes.buffer);
    bytes[0] = 0;
    bytes.set(colorBytes(action.color), 1);
    bytes[4] = action.width;
    action.points.forEach((point, index) => {
      const offset = PATH_HEADER_SIZE + index * PATH_POINT_SIZE;
      view.setInt16(offset, Math.round(point.x * CANVAS_COORDINATE_SCALE), true);
      view.setInt16(offset + 2, Math.round(point.y * CANVAS_COORDINATE_SCALE), true);
    });
    return bytes;
  }
  if (action.kind === "shape") {
    const bytes = new Uint8Array(SHAPE_ACTION_SIZE);
    const view = new DataView(bytes.buffer);
    bytes[0] = 1;
    bytes[1] = HISTORY_SHAPES.indexOf(action.payload.shape);
    bytes.set(colorBytes(action.payload.color), 2);
    bytes[5] = action.payload.width;
    view.setInt16(6, Math.round(
      action.payload.from.x * CANVAS_WIDTH * CANVAS_COORDINATE_SCALE,
    ), true);
    view.setInt16(8, Math.round(
      action.payload.from.y * CANVAS_HEIGHT * CANVAS_COORDINATE_SCALE,
    ), true);
    view.setInt16(10, Math.round(
      action.payload.to.x * CANVAS_WIDTH * CANVAS_COORDINATE_SCALE,
    ), true);
    view.setInt16(12, Math.round(
      action.payload.to.y * CANVAS_HEIGHT * CANVAS_COORDINATE_SCALE,
    ), true);
    return bytes;
  }
  if (action.kind === "fill") {
    const bytes = new Uint8Array(FILL_ACTION_SIZE);
    const view = new DataView(bytes.buffer);
    bytes[0] = 2;
    bytes.set(colorBytes(action.color), 1);
    view.setUint16(4, action.x, true);
    view.setUint16(6, action.y, true);
    return bytes;
  }
  if (action.kind === "checkpoint") {
    const bytes = new Uint8Array(CHECKPOINT_HEADER_SIZE + action.png.byteLength);
    const view = new DataView(bytes.buffer);
    bytes[0] = 4;
    view.setUint32(1, action.png.byteLength, true);
    bytes.set(action.png, CHECKPOINT_HEADER_SIZE);
    return bytes;
  }
  return Uint8Array.of(3);
}

function extendHistoryHash(previous: number, action: DecodedCanvasAction): number {
  const record = canonicalActionBytes(action);
  const length = new Uint8Array(4);
  new DataView(length.buffer).setUint32(0, record.byteLength, true);
  return crc32(record, crc32(length, previous));
}

export function calculateCanvasHistoryHash(
  actions: DecodedCanvasAction[],
): number {
  return actions.reduce(extendHistoryHash, 0);
}

export function actionReplayWork(action: DecodedCanvasAction): number {
  if (action.kind === "path") return PATH_WORK;
  if (action.kind === "shape") return SHAPE_WORK;
  if (action.kind === "fill") return FILL_WORK;
  if (action.kind === "checkpoint") return CHECKPOINT_WORK;
  return CLEAR_WORK;
}

export function actionPointCount(action: DecodedCanvasAction): number {
  return action.kind === "path" ? action.points.length : 0;
}

export function semanticStart(actions: DecodedCanvasAction[]): number {
  return actions[0]?.kind === "checkpoint" ? 1 : 0;
}

export function windowReplayWork(actions: DecodedCanvasAction[]): number {
  return actions.reduce((total, action) => total + actionReplayWork(action), 0);
}

export function windowPointCount(actions: DecodedCanvasAction[]): number {
  return actions.reduce((total, action) => total + actionPointCount(action), 0);
}

export function neededFoldCount(
  actions: DecodedCanvasAction[],
  extraWork: number,
  extraPoints: number,
  extraActions: number,
  foldableCount?: number,
): number | null | -1 {
  const start = semanticStart(actions);
  const semantic = actions.length - start;
  const foldable = Math.min(foldableCount ?? semantic, semantic);
  const work = windowReplayWork(actions);
  const points = windowPointCount(actions);
  if (
    work + extraWork <= MAX_WINDOW_WORK
    && semantic + extraActions <= MAX_WINDOW_ACTIONS
    && points + extraPoints <= MAX_CANVAS_POINTS
  ) {
    return null;
  }
  let foldedWork = 0;
  let foldedPoints = 0;
  for (let folded = 1; folded <= foldable; folded++) {
    const action = actions[start + folded - 1];
    foldedWork += actionReplayWork(action);
    foldedPoints += actionPointCount(action);
    if (
      work - foldedWork + extraWork <= MAX_WINDOW_WORK
      && semantic - folded + extraActions <= MAX_WINDOW_ACTIONS
      && points - foldedPoints + extraPoints <= MAX_CANVAS_POINTS
    ) {
      return folded;
    }
  }
  return -1;
}

function packetCost(packet: LiveDrawingPacket): {
  extraWork: number;
  extraPoints: number;
  extraActions: number;
} | null {
  if (packet.event === "draw_start") {
    return { extraWork: PATH_WORK, extraPoints: 1, extraActions: 1 };
  }
  if (packet.event === "draw_shape") {
    return { extraWork: SHAPE_WORK, extraPoints: 0, extraActions: 1 };
  }
  if (packet.event === "draw_fill") {
    return { extraWork: FILL_WORK, extraPoints: 0, extraActions: 1 };
  }
  if (packet.event === "clear_canvas") {
    return { extraWork: CLEAR_WORK, extraPoints: 0, extraActions: 1 };
  }
  if (packet.event === "draw_move") {
    return { extraWork: 0, extraPoints: packet.payload.points.length, extraActions: 0 };
  }
  return { extraWork: 0, extraPoints: 0, extraActions: 0 };
}

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
  generation: number | null = null;
  sequence: number | null = null;
  historyHash: number | null = null;
  private activePath: Extract<DecodedCanvasAction, { kind: "path" }> | null = null;
  private prefixHashes: number[] = [];

  replace(
    actions: DecodedCanvasAction[],
    revision: unknown,
    generation: unknown,
    sequence: unknown,
    historyHash: unknown,
  ): boolean {
    if (
      !isRevision(revision)
      || !isRevision(generation)
      || generation === 0
      || !isRevision(sequence)
      || !isRevision(historyHash)
      || historyHash > 0xffffffff
    ) return false;
    const prefixHashes: number[] = [];
    for (const action of actions) {
      prefixHashes.push(extendHistoryHash(prefixHashes.at(-1) ?? 0, action));
    }
    if ((prefixHashes.at(-1) ?? 0) !== historyHash) return false;
    this.actions = actions;
    this.revision = revision;
    this.generation = generation;
    this.sequence = sequence;
    this.historyHash = historyHash;
    this.prefixHashes = prefixHashes;
    this.activePath = null;
    return true;
  }

  reset(payload: unknown): boolean {
    if (
      !Array.isArray(payload)
      || payload.length !== 4
      || !isRevision(payload[0])
      || !isRevision(payload[1])
      || payload[1] === 0
      || payload[2] !== 0
      || payload[3] !== 0
    ) return false;
    this.actions = [];
    this.revision = payload[0];
    this.generation = payload[1];
    this.sequence = 0;
    this.historyHash = 0;
    this.prefixHashes = [];
    this.activePath = null;
    return true;
  }

  canApply(packet: LiveDrawingPacket): boolean {
    if (
      packet.event === "clear_canvas"
      && (this.actions.length === 0 || this.actions.at(-1)?.kind === "clear")
    ) {
      return false;
    }
    const cost = packetCost(packet);
    if (!cost) return false;
    if (packet.event === "draw_move") {
      if (!this.activePath && this.actions.at(-1)?.kind !== "path") return false;
      return windowPointCount(this.actions) + cost.extraPoints <= MAX_CANVAS_POINTS;
    }
    if (packet.event === "draw_end") {
      return Boolean(this.activePath || this.actions.at(-1)?.kind === "path");
    }
    const needed = neededFoldCount(
      this.actions.at(-1)?.kind === "clear" ? [] : this.actions,
      cost.extraWork,
      cost.extraPoints,
      cost.extraActions,
      this.actions.at(-1)?.kind === "path" && this.activePath
        ? this.actions.length - semanticStart(this.actions) - 1
        : undefined,
    );
    return needed !== -1;
  }

  neededFoldForPacket(packet: LiveDrawingPacket): number | null {
    const cost = packetCost(packet);
    if (!cost || cost.extraActions === 0 && packet.event !== "draw_move") return null;
    if (packet.event === "draw_move" || packet.event === "draw_end") return null;
    const needed = neededFoldCount(
      this.actions.at(-1)?.kind === "clear" ? [] : this.actions,
      cost.extraWork,
      cost.extraPoints,
      cost.extraActions,
    );
    return typeof needed === "number" && needed > 0 ? needed : null;
  }

  opportunisticFoldCount(threshold = 0.8): number | null {
    const needed = neededFoldCount(
      this.actions,
      MAX_WINDOW_WORK - Math.floor(MAX_WINDOW_WORK * threshold),
      MAX_CANVAS_POINTS - Math.floor(MAX_CANVAS_POINTS * threshold),
      MAX_WINDOW_ACTIONS - Math.max(1, Math.floor(MAX_WINDOW_ACTIONS * threshold)),
    );
    return typeof needed === "number" && needed > 0 ? needed : null;
  }

  applyCheckpoint(png: Uint8Array, foldedCount: number): boolean {
    if (png.byteLength > MAX_CHECKPOINT_PNG) return false;
    if (PNG_SIGNATURE.some((byte, index) => png[index] !== byte)) return false;
    const start = semanticStart(this.actions);
    const semantic = this.actions.length - start;
    if (foldedCount < 1 || foldedCount > semantic) return false;
    if (this.activePath && foldedCount > semantic - 1) return false;
    const remaining = this.actions.slice(start + foldedCount);
    this.actions = [{ kind: "checkpoint", png: new Uint8Array(png) }, ...remaining];
    this.prefixHashes = [];
    for (const action of this.actions) {
      this.prefixHashes.push(extendHistoryHash(this.prefixHashes.at(-1) ?? 0, action));
    }
    this.historyHash = this.prefixHashes.at(-1) ?? 0;
    this.advanceRevision();
    if (this.activePath) {
      this.activePath = remaining.at(-1)?.kind === "path"
        ? remaining.at(-1) as Extract<DecodedCanvasAction, { kind: "path" }>
        : null;
    }
    return true;
  }

  prefixHashForFold(foldedCount: number): number | null {
    const start = semanticStart(this.actions);
    return this.prefixHashes[start + foldedCount - 1] ?? null;
  }

  checkpointPng(): Uint8Array | null {
    const first = this.actions[0];
    return first?.kind === "checkpoint" ? first.png : null;
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
      if (windowPointCount(this.actions) + packet.payload.points.length > MAX_CANVAS_POINTS) {
        return false;
      }
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
      this.finalizeLastAction();
      return true;
    }
    if (packet.event === "clear_canvas") {
      if (this.actions.length === 0 || this.actions.at(-1)?.kind === "clear") {
        return false;
      }
      if (neededFoldCount(this.actions, CLEAR_WORK, 0, 1) !== null) return false;
      this.actions.push({ kind: "clear" });
      this.activePath = null;
      this.advanceRevision();
      this.finalizeLastAction();
      return true;
    }

    // Starting a new action after Clear permanently discards the pre-clear
    // history, matching Game.record_stroke on the server.
    if (this.actions.at(-1)?.kind === "clear") {
      this.actions = [];
      this.prefixHashes = [];
      this.historyHash = 0;
    }
    this.activePath = null;

    const cost = packetCost(packet);
    if (!cost || neededFoldCount(
      this.actions,
      cost.extraWork,
      cost.extraPoints,
      cost.extraActions,
    ) !== null) {
      return false;
    }

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
    if (packet.event !== "draw_start") this.finalizeLastAction();
    return true;
  }

  prepareUndo(
    sequence: number,
  ): [
    generation: number,
    sequence: number,
    fromRevision: number,
    fromHash: number,
  ] | null {
    if (
      this.revision === null
      || this.generation === null
      || this.sequence === null
      || this.historyHash === null
      || !isRevision(sequence)
      || sequence <= this.sequence
      || this.actions.length === 0
      || this.actions.at(-1)?.kind === "checkpoint"
    ) return null;
    const request: [number, number, number, number] = [
      this.generation,
      sequence,
      this.revision,
      this.historyHash,
    ];
    this.actions.pop();
    this.prefixHashes.length = this.actions.length;
    this.historyHash = this.prefixHashes.at(-1) ?? 0;
    this.revision += 1;
    this.activePath = null;
    return request;
  }

  confirmAction(
    payload: unknown,
    expectedRevision = this.revision,
    expectedHash = this.historyHash,
  ): boolean {
    if (
      !Array.isArray(payload)
      || payload.length < 4
      || !isRevision(payload[0])
      || !isRevision(payload[1])
      || !isRevision(payload[2])
      || !isRevision(payload[3])
      || payload[3] > 0xffffffff
      || this.generation === null
      || this.sequence === null
      || payload[0] !== this.generation
      || payload[1] !== this.sequence + 1
      || payload[2] !== expectedRevision
      || payload[3] !== expectedHash
    ) {
      return false;
    }
    this.sequence = payload[1];
    return true;
  }

  confirmUndo(
    payload: unknown,
    expectedRevision?: number,
    expectedHash?: number,
  ): boolean {
    if (
      !Array.isArray(payload)
      || payload.length !== 5
      || !isRevision(payload[0])
      || !isRevision(payload[1])
      || !isRevision(payload[2])
      || !isRevision(payload[3])
      || !isRevision(payload[4])
      || payload[4] > 0xffffffff
      || payload[3] !== payload[2] + 1
      || this.generation === null
      || this.sequence === null
      || payload[0] !== this.generation
      || payload[1] !== this.sequence + 1
    ) return false;

    if (expectedRevision !== undefined || expectedHash !== undefined) {
      if (
        payload[3] !== expectedRevision
        || payload[4] !== expectedHash
      ) return false;
      this.sequence = payload[1];
      return true;
    }

    if (this.revision === payload[2]) {
      if (this.actions.length === 0) return false;
      this.actions.pop();
      this.prefixHashes.length = this.actions.length;
      this.historyHash = this.prefixHashes.at(-1) ?? 0;
      this.revision = payload[3];
      this.activePath = null;
    } else if (this.revision !== payload[3]) {
      return false;
    }
    if (this.historyHash !== payload[4]) return false;
    this.sequence = payload[1];
    return true;
  }

  private advanceRevision(): void {
    if (this.revision !== null) this.revision += 1;
  }

  private finalizeLastAction(): void {
    if (this.actions.length === 0) return;
    this.prefixHashes.length = this.actions.length - 1;
    this.prefixHashes.push(extendHistoryHash(
      this.prefixHashes.at(-1) ?? 0,
      this.actions.at(-1)!,
    ));
    this.historyHash = this.prefixHashes.at(-1)!;
  }
}

function historyWindowValid(actions: DecodedCanvasAction[]): boolean {
  const start = semanticStart(actions);
  if (actions.some((action, index) => action.kind === "checkpoint" && index !== 0)) {
    return false;
  }
  return (
    actions.length - start <= MAX_WINDOW_ACTIONS
    && windowReplayWork(actions) <= MAX_WINDOW_WORK
    && windowPointCount(actions) <= MAX_CANVAS_POINTS
  );
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
    if (!Array.isArray(rawAction) || !isIntegerBetween(rawAction[0], 0, 4)) return null;
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
    } else if (tag === 4) {
      if (
        decoded.length !== 0
        || rawAction.length !== 2
        || typeof rawAction[1] !== "string"
      ) {
        return null;
      }
      try {
        const binary = atob(rawAction[1]);
        const png = Uint8Array.from(binary, (character) => character.charCodeAt(0));
        if (
          png.byteLength > MAX_CHECKPOINT_PNG
          || PNG_SIGNATURE.some((byte, offset) => png[offset] !== byte)
        ) {
          return null;
        }
        decoded.push({ kind: "checkpoint", png });
      } catch {
        return null;
      }
    } else {
      if (rawAction.length !== 1) return null;
      decoded.push({ kind: "clear" });
    }
  }
  return historyWindowValid(decoded) ? decoded : null;
}

export function binaryDataView(payload: unknown): DataView | null {
  if (payload instanceof ArrayBuffer) return new DataView(payload);
  if (ArrayBuffer.isView(payload)) {
    return new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
  }
  return null;
}

export function binaryColor(view: DataView, offset: number): string {
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
  if (actionCount > MAX_CANVAS_ACTIONS || view.byteLength > MAX_SYNC_BYTES) return null;
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
    } else if (tag === 4) {
      if (index !== 0 || recordLength < CHECKPOINT_HEADER_SIZE) return null;
      const length = view.getUint32(start + 1, true);
      if (length !== recordLength - CHECKPOINT_HEADER_SIZE) return null;
      if (length > MAX_CHECKPOINT_PNG) return null;
      const png = new Uint8Array(view.buffer, view.byteOffset + start + CHECKPOINT_HEADER_SIZE, length);
      if (PNG_SIGNATURE.some((byte, offset) => png[offset] !== byte)) return null;
      decoded.push({ kind: "checkpoint", png: new Uint8Array(png) });
    } else {
      return null;
    }
  }
  return historyWindowValid(decoded) ? decoded : null;
}

export function decodeCanvasHistory(payload: unknown): DecodedCanvasAction[] | null {
  const binary = binaryDataView(payload);
  return binary
    ? decodeBinaryCanvasHistory(binary)
    : decodeJsonCanvasHistory(payload);
}
