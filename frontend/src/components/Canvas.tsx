import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import {
  CANVAS_COORDINATE_SCALE,
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  ClientCanvasHistory,
  decodeCanvasHistory,
} from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { registerCanvasCommandHandlers } from "../lib/canvasCommands";
import {
  encodeClear,
  decodeLiveDrawing,
  encodeFill,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
  encodeShape,
} from "../lib/liveDrawing";
import { emitWithAck, socket } from "../lib/socket";
import { useSettingsStore } from "../store/settingsStore";
import type {
  DrawTool,
  ShapeType,
  StrokeFillPayload,
  StrokeMovePayload,
  StrokePoint,
  StrokeShapePayload,
  StrokeStartPayload,
} from "../types";

const FLUSH_INTERVAL_MS = 40;
const MAX_PENDING_CANVAS_ACTIONS = 256;

type DrawingFrame = number | Uint8Array;
type PendingCanvasMutation =
  | {
    kind: "draw";
    generation: number;
    frames: DrawingFrame[];
    expectedRevision: number | null;
    expectedHash: number | null;
  }
  | {
    kind: "undo";
    generation: number;
    request: [
      generation: number,
      sequence: number,
      fromRevision: number,
      fromHash: number,
    ];
    expectedRevision: number;
    expectedHash: number;
  };

interface CanvasProps {
  isDrawer: boolean;
  color: string;
  brushWidth: number;
  tool: DrawTool;
  solutionWord?: string | null;
  overlay?: ReactNode;
}

function getYYMMDDhhmm(d = new Date()): string {
  const yy = String(d.getFullYear()).slice(-2);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${yy}${mm}${dd}${hh}${min}`;
}

function sanitizePrompt(prompt: string): string {
  return prompt
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9_-]/g, "");
}

function toPixels(p: StrokePoint) {
  return { x: p.x * CANVAS_WIDTH, y: p.y * CANVAS_HEIGHT };
}

// Draws a rectangle/ellipse/triangle outline inscribed in the bounding box defined by
// `from`/`to` (normalized 0-1 points). Shared by local commit, remote render, and preview.
function drawShapeOutline(
  ctx: CanvasRenderingContext2D,
  from: StrokePoint,
  to: StrokePoint,
  shape: ShapeType,
  strokeColor: string,
  strokeWidth: number,
) {
  const a = toPixels(from);
  const b = toPixels(to);
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const w = Math.abs(b.x - a.x);
  const h = Math.abs(b.y - a.y);

  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = strokeWidth;
  ctx.beginPath();
  if (shape === "rectangle") {
    ctx.rect(x, y, w, h);
  } else if (shape === "ellipse") {
    ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
  } else {
    ctx.moveTo(x + w / 2, y);
    ctx.lineTo(x, y + h);
    ctx.lineTo(x + w, y + h);
    ctx.closePath();
  }
  ctx.stroke();
}

function hexToRgba(hex: string): [number, number, number, number] {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.substring(0, 2), 16) || 0;
  const g = parseInt(clean.substring(2, 4), 16) || 0;
  const b = parseInt(clean.substring(4, 6), 16) || 0;
  return [r, g, b, 255];
}

// The drawing canvas's "empty" appearance comes purely from the white CSS
// background showing through an untouched (fully transparent) canvas
// element. That mismatch matters once white becomes a real drawable color:
// a white stroke over blank canvas would write opaque white pixel data
// sitting right next to transparent "blank" pixels - an invisible boundary
// to the eye, but a very real one to flood fill, which would then refuse to
// flow across it. Painting the canvas with actual opaque white up front -
// and every time it's cleared - keeps the underlying pixel data consistent
// with what's visible, so a white stroke is indistinguishable from blank
// canvas everywhere it matters.
function fillWhite(ctx: CanvasRenderingContext2D, width: number, height: number): void {
  ctx.save();
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  ctx.restore();
}

function colorsEqual(data: Uint8ClampedArray, index: number, target: [number, number, number, number]): boolean {
  return (
    data[index] === target[0] &&
    data[index + 1] === target[1] &&
    data[index + 2] === target[2] &&
    data[index + 3] === target[3]
  );
}

// Brave's fingerprinting protection can slightly perturb values returned by
// canvas readback APIs. Those differences are visually imperceptible, but an
// exact-match flood fill treats every perturbed pixel as a separate region
// and leaves high-contrast pinholes behind. Keep the tolerance deliberately
// small: it absorbs readback noise while preserving visibly distinct colors
// as fill boundaries.
const FLOOD_FILL_CHANNEL_TOLERANCE = 8;

function colorsMatchForFill(
  data: Uint8ClampedArray,
  index: number,
  target: [number, number, number, number],
): boolean {
  return (
    Math.abs(data[index] - target[0]) <= FLOOD_FILL_CHANNEL_TOLERANCE
    && Math.abs(data[index + 1] - target[1]) <= FLOOD_FILL_CHANNEL_TOLERANCE
    && Math.abs(data[index + 2] - target[2]) <= FLOOD_FILL_CHANNEL_TOLERANCE
    && Math.abs(data[index + 3] - target[3]) <= FLOOD_FILL_CHANNEL_TOLERANCE
  );
}

interface Point {
  x: number;
  y: number;
}

interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function boundsFromPath(points: Point[], radius: number): Bounds {
  let minX = points[0].x;
  let minY = points[0].y;
  let maxX = points[0].x;
  let maxY = points[0].y;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  const pad = radius + 1;
  return { minX: minX - pad, minY: minY - pad, maxX: maxX + pad, maxY: maxY + pad };
}

// Squared distance from a point to a segment [a, b] - used to test whether a
// pixel falls within a thick line's "capsule" (a rectangle with semicircular
// round caps at each end), which is exactly what a round-linecap stroke of a
// given radius covers.
function distanceToSegmentSquared(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) {
    const ex = px - ax;
    const ey = py - ay;
    return ex * ex + ey * ey;
  }
  let t = ((px - ax) * dx + (py - ay) * dy) / lengthSquared;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  const ex = px - cx;
  const ey = py - cy;
  return ex * ex + ey * ey;
}

// Rasterizes a thick path directly into pixel data instead of asking
// Canvas 2D to stroke it. Canvas 2D's path rasterizer always anti-aliases
// (there's no flag to disable it for strokes/fills, unlike
// `imageSmoothingEnabled`, which only affects `drawImage`), leaving a fringe
// of partially-blended pixels along every edge that are neither the drawn
// color nor the prior background - which made flood fill unreliable, and
// every workaround for it (tolerance matching, eroding/dilating the fill
// region, or post-hoc snapping pixels to the nearer of two colors) fragile
// in its own way. Testing each pixel directly against the geometry
// sidesteps the problem instead of patching around it: every pixel this
// touches is set to exactly `color`, or left exactly as it was - never
// anything in between.
//
// Each consecutive pair of points (and, if `closed`, the pair wrapping from
// the last point back to the first) is treated as a capsule of the given
// radius: a pixel is set to `color` if its center falls within `radius` of
// that segment. A single point drawn as [p, p] naturally becomes a filled
// circle (a degenerate, zero-length capsule), which is how a lone click/tap
// renders as a dot.
function rasterizePath(
  ctx: CanvasRenderingContext2D,
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
  const w = right - x;
  const h = bottom - y;
  if (w <= 0 || h <= 0) return;

  const imageData = ctx.getImageData(x, y, w, h);
  const data = imageData.data;
  const radiusSquared = radius * radius;
  const segmentCount = closed ? points.length : points.length - 1;

  for (let s = 0; s < segmentCount; s++) {
    const a = points[s];
    const b = points[(s + 1) % points.length];
    const segMinX = Math.max(0, Math.floor(Math.min(a.x, b.x) - radius - x));
    const segMinY = Math.max(0, Math.floor(Math.min(a.y, b.y) - radius - y));
    const segMaxX = Math.min(w - 1, Math.ceil(Math.max(a.x, b.x) + radius - x));
    const segMaxY = Math.min(h - 1, Math.ceil(Math.max(a.y, b.y) + radius - y));
    for (let py = segMinY; py <= segMaxY; py++) {
      for (let px = segMinX; px <= segMaxX; px++) {
        const worldX = px + x + 0.5;
        const worldY = py + y + 0.5;
        if (distanceToSegmentSquared(worldX, worldY, a.x, a.y, b.x, b.y) <= radiusSquared) {
          const idx = (py * w + px) * 4;
          data[idx] = color[0];
          data[idx + 1] = color[1];
          data[idx + 2] = color[2];
          data[idx + 3] = color[3];
        }
      }
    }
  }

  ctx.putImageData(imageData, x, y);
}

// Rasterizes a multi-point polyline in a single getImageData / putImageData operation,
// avoiding N individual canvas readbacks for multi-point draw_move payloads and replay logs.
function rasterizePolyline(
  ctx: CanvasRenderingContext2D,
  points: Point[],
  radius: number,
  color: [number, number, number, number],
): void {
  if (points.length === 0) return;
  if (points.length === 1) {
    rasterizePath(ctx, points, radius, color, false);
    return;
  }
  const bounds = boundsFromPath(points, radius);
  const x = Math.max(0, Math.floor(bounds.minX));
  const y = Math.max(0, Math.floor(bounds.minY));
  const right = Math.min(CANVAS_WIDTH, Math.ceil(bounds.maxX));
  const bottom = Math.min(CANVAS_HEIGHT, Math.ceil(bounds.maxY));
  const w = right - x;
  const h = bottom - y;
  if (w <= 0 || h <= 0) return;

  const imageData = ctx.getImageData(x, y, w, h);
  const data = imageData.data;
  const radiusSquared = radius * radius;
  const segmentCount = points.length - 1;

  for (let s = 0; s < segmentCount; s++) {
    const a = points[s];
    const b = points[s + 1];
    const segMinX = Math.max(0, Math.floor(Math.min(a.x, b.x) - radius - x));
    const segMinY = Math.max(0, Math.floor(Math.min(a.y, b.y) - radius - y));
    const segMaxX = Math.min(w - 1, Math.ceil(Math.max(a.x, b.x) + radius - x));
    const segMaxY = Math.min(h - 1, Math.ceil(Math.max(a.y, b.y) + radius - y));
    for (let py = segMinY; py <= segMaxY; py++) {
      for (let px = segMinX; px <= segMaxX; px++) {
        const worldX = px + x + 0.5;
        const worldY = py + y + 0.5;
        if (distanceToSegmentSquared(worldX, worldY, a.x, a.y, b.x, b.y) <= radiusSquared) {
          const idx = (py * w + px) * 4;
          data[idx] = color[0];
          data[idx + 1] = color[1];
          data[idx + 2] = color[2];
          data[idx + 3] = color[3];
        }
      }
    }
  }

  ctx.putImageData(imageData, x, y);
}

const ELLIPSE_OUTLINE_SEGMENTS = 96;

// Same inscribed-rectangle geometry as drawShapeOutline (still used as-is
// for the live drag preview, which is transient and never flood-filled so
// its anti-aliasing doesn't matter), but returning perimeter vertices for
// rasterizePath instead of tracing a Path2D.
function shapeOutlinePoints(from: StrokePoint, to: StrokePoint, shape: ShapeType): Point[] {
  const a = toPixels(from);
  const b = toPixels(to);
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const w = Math.abs(b.x - a.x);
  const h = Math.abs(b.y - a.y);

  if (shape === "rectangle") {
    return [
      { x, y },
      { x: x + w, y },
      { x: x + w, y: y + h },
      { x, y: y + h },
    ];
  }
  if (shape === "ellipse") {
    const cx = x + w / 2;
    const cy = y + h / 2;
    const rx = w / 2;
    const ry = h / 2;
    const points: Point[] = [];
    for (let i = 0; i < ELLIPSE_OUTLINE_SEGMENTS; i++) {
      const angle = (i / ELLIPSE_OUTLINE_SEGMENTS) * Math.PI * 2;
      points.push({ x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle) });
    }
    return points;
  }
  return [
    { x: x + w / 2, y },
    { x, y: y + h },
    { x: x + w, y: y + h },
  ];
}

function drawShapeOutlinePixels(
  ctx: CanvasRenderingContext2D,
  from: StrokePoint,
  to: StrokePoint,
  shape: ShapeType,
  strokeColor: string,
  strokeWidth: number,
): void {
  rasterizePath(ctx, shapeOutlinePoints(from, to, shape), strokeWidth / 2, hexToRgba(strokeColor), true);
}

// Stack-based 8-connected flood fill, mutating `imageData.data` in place and
// returning whether it changed any pixels (false when the clicked pixel
// already exactly matches the fill color). 8-connectivity
// (orthogonal + diagonal neighbors) is used rather than plain 4-connectivity
// so that regions which only touch corner-to-corner - e.g. the pinched tip
// of a triangle, or two areas separated by a thin single-pixel-wide
// staircased diagonal line - are still treated as the same fillable region
// instead of leaving an unfilled sliver behind. Since every stroke is
// rasterized directly into pixel data (see rasterizePath) rather than
// through Canvas 2D's anti-aliased stroke/fill, the canvas only ever
// contains flat colors. Region matching allows only a small per-channel
// tolerance to compensate for browsers that deliberately perturb canvas
// readback values for fingerprinting protection; this avoids noisy holes
// without dilating the region or changing its geometric boundaries. Matching
// remains pixel-based, so it naturally respects whatever shape the rendered
// strokes happen to form - including sub-regions carved out by
// self-intersecting lines, which have no explicit notion of "closed path" on
// a raster canvas.
function floodFillPixels(
  imageData: ImageData,
  startX: number,
  startY: number,
  fillColor: [number, number, number, number],
): boolean {
  const { width, height, data } = imageData;
  const startIndex = (startY * width + startX) * 4;
  if (colorsEqual(data, startIndex, fillColor)) return false;
  const target: [number, number, number, number] = [
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

function applyFillAtPixel(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  color: string,
): boolean {
  if (x < 0 || x >= CANVAS_WIDTH || y < 0 || y >= CANVAS_HEIGHT) return false;
  const imageData = ctx.getImageData(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
  if (!floodFillPixels(imageData, x, y, hexToRgba(color))) return false;
  ctx.putImageData(imageData, 0, 0);
  return true;
}

function applyFillAction(ctx: CanvasRenderingContext2D, payload: StrokeFillPayload): boolean {
  return applyFillAtPixel(
    ctx,
    Math.floor(payload.x * CANVAS_WIDTH),
    Math.floor(payload.y * CANVAS_HEIGHT),
    payload.color,
  );
}

export interface CanvasRef {
  saveImage: () => void;
  getImageDataUrl: () => string | null;
}

export const Canvas = forwardRef<CanvasRef, CanvasProps>(function Canvas(
  {
    isDrawer,
    color,
    brushWidth,
    tool,
    solutionWord = null,
    overlay = null,
  }: CanvasProps,
  ref
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);
  const previewCtxRef = useRef<CanvasRenderingContext2D | null>(null);
  const isPointerDownRef = useRef(false);
  const activePointerIdRef = useRef<number | null>(null);
  const pendingPointsRef = useRef<StrokePoint[]>([]);
  const lastPointRef = useRef<StrokePoint | null>(null);
  const shapeStartRef = useRef<StrokePoint | null>(null);
  const replayGenerationRef = useRef(0);
  const historyRef = useRef(new ClientCanvasHistory());
  const nextSequenceRef = useRef(1);
  const pendingMutationsRef = useRef(new Map<number, PendingCanvasMutation>());
  const activeOutgoingSequenceRef = useRef<number | null>(null);

  const allocateSequence = useCallback((): number | null => {
    if (pendingMutationsRef.current.size >= MAX_PENDING_CANVAS_ACTIONS) {
      socket.emit("request_sync_strokes");
      return null;
    }
    const sequence = nextSequenceRef.current;
    nextSequenceRef.current += 1;
    return sequence;
  }, []);

  const beginDrawAction = useCallback((
    frame: DrawingFrame,
    isPath = false,
  ): number | null => {
    const sequence = allocateSequence();
    const generation = historyRef.current.generation;
    if (sequence === null || generation === null) {
      socket.emit("request_sync_strokes");
      return null;
    }
    const history = historyRef.current;
    pendingMutationsRef.current.set(sequence, {
      kind: "draw",
      generation,
      frames: [frame],
      expectedRevision: isPath ? null : history.revision,
      expectedHash: isPath ? null : history.historyHash,
    });
    activeOutgoingSequenceRef.current = isPath ? sequence : null;
    socket.emit("draw", frame, [generation, sequence]);
    return sequence;
  }, [allocateSequence]);

  const sendPathFrame = useCallback((frame: DrawingFrame): void => {
    const sequence = activeOutgoingSequenceRef.current;
    if (sequence === null) return;
    const pending = pendingMutationsRef.current.get(sequence);
    if (!pending || pending.kind !== "draw") return;
    pending.frames.push(frame);
    socket.emit("draw", frame);
  }, []);

  const finishPathAction = useCallback((): void => {
    const sequence = activeOutgoingSequenceRef.current;
    if (sequence === null) return;
    const pending = pendingMutationsRef.current.get(sequence);
    if (pending?.kind === "draw") {
      pending.expectedRevision = historyRef.current.revision;
      pending.expectedHash = historyRef.current.historyHash;
    }
    activeOutgoingSequenceRef.current = null;
  }, []);

  const requestAuthoritativeSync = useCallback((discardPending = true): void => {
    if (discardPending) {
      pendingMutationsRef.current.clear();
      activeOutgoingSequenceRef.current = null;
    }
    socket.emit("request_sync_strokes");
  }, []);

  const finalizeActivePath = useCallback((): void => {
    if (activeOutgoingSequenceRef.current === null) return;
    if (pendingPointsRef.current.length > 0) {
      sendPathFrame(encodePathPoints({ points: pendingPointsRef.current }));
      pendingPointsRef.current = [];
    }
    historyRef.current.apply({ event: "draw_end", payload: {} });
    sendPathFrame(encodePathEnd());
    finishPathAction();
    activePointerIdRef.current = null;
    isPointerDownRef.current = false;
    lastPointRef.current = null;
  }, [finishPathAction, sendPathFrame]);

  useImperativeHandle(ref, () => ({
    saveImage: handleSaveImage,
    getImageDataUrl: () => canvasRef.current?.toDataURL("image/png") ?? null,
  }));

  // If the turn ends (isDrawer flips to false) while the drawer is still
  // physically holding the pointer down mid-stroke, the real "pointer up"
  // only fires afterwards - and handlePointerUp bails out immediately once
  // isDrawer is false, so it never clears isPointerDownRef/lastPointRef.
  // Left stale, the next time this player becomes the drawer again, the
  // very first pointer move would see isPointerDownRef still true and draw
  // a spurious segment from that old leftover point to the current cursor
  // position. Reset all in-progress pointer/shape state as soon as drawing
  // rights are taken away, regardless of whether a pointer up ever arrives.
  useEffect(() => {
    if (isDrawer) return;
    activePointerIdRef.current = null;
    isPointerDownRef.current = false;
    pendingPointsRef.current = [];
    lastPointRef.current = null;
    shapeStartRef.current = null;
    pointerPosRef.current = null;
    const preview = previewCanvasRef.current;
    const previewCtx = previewCtxRef.current;
    if (preview && previewCtx) previewCtx.clearRect(0, 0, preview.width, preview.height);
  }, [isDrawer]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    fillWhite(ctx, canvas.width, canvas.height);
    ctxRef.current = ctx;

    const preview = previewCanvasRef.current;
    if (!preview) return;
    const previewCtx = preview.getContext("2d");
    if (!previewCtx) return;
    previewCtx.lineCap = "round";
    previewCtx.lineJoin = "round";
    previewCtxRef.current = previewCtx;
  }, []);

  // Periodically flush batched local pointer-move points to the server.
  useEffect(() => {
    const flushTimer = setInterval(() => {
      if (pendingPointsRef.current.length === 0) return;
      const points = pendingPointsRef.current;
      pendingPointsRef.current = [];
      sendPathFrame(encodePathPoints({ points }));
    }, FLUSH_INTERVAL_MS);
    return () => clearInterval(flushTimer);
  }, [sendPathFrame]);

  // Render strokes coming from the current drawer (remote to this client).
  useEffect(() => {
    function drawSegmentOn(
      ctx: CanvasRenderingContext2D,
      from: StrokePoint,
      to: StrokePoint,
      strokeColor: string,
      strokeWidth: number,
    ) {
      rasterizePolyline(ctx, [toPixels(from), toPixels(to)], strokeWidth / 2, hexToRgba(strokeColor));
    }

    function drawShapeOn(ctx: CanvasRenderingContext2D, payload: StrokeShapePayload) {
      drawShapeOutlinePixels(ctx, payload.from, payload.to, payload.shape, payload.color, payload.width);
    }

    function drawSegment(from: StrokePoint, to: StrokePoint, strokeColor: string, strokeWidth: number) {
      const ctx = ctxRef.current;
      if (!ctx) return;
      drawSegmentOn(ctx, from, to, strokeColor, strokeWidth);
    }

    const remoteState: { last: StrokePoint | null; color: string; width: number } = {
      last: null,
      color: "#000000",
      width: 4,
    };

    const onDrawStart = (payload: StrokeStartPayload) => {
      remoteState.last = { x: payload.x, y: payload.y };
      remoteState.color = payload.color;
      remoteState.width = payload.width;
      drawSegment(remoteState.last, remoteState.last, remoteState.color, remoteState.width);
    };

    const onDrawMove = (payload: StrokeMovePayload) => {
      const ctx = ctxRef.current;
      if (!ctx || payload.points.length === 0) return;
      if (remoteState.last) {
        const polyline: Point[] = [toPixels(remoteState.last)];
        for (const pt of payload.points) {
          polyline.push(toPixels(pt));
        }
        rasterizePolyline(ctx, polyline, remoteState.width / 2, hexToRgba(remoteState.color));
      }
      remoteState.last = payload.points[payload.points.length - 1];
    };

    const onDrawEnd = () => {
      remoteState.last = null;
    };

    const onDrawShape = (payload: StrokeShapePayload) => {
      const ctx = ctxRef.current;
      if (!ctx) return;
      drawShapeOn(ctx, payload);
    };

    const onDrawFill = (payload: StrokeFillPayload) => {
      const ctx = ctxRef.current;
      if (!ctx) return;
      applyFillAction(ctx, payload);
    };

    const onClearCanvas = () => {
      replayGenerationRef.current += 1;
      const canvas = canvasRef.current;
      const ctx = ctxRef.current;
      if (canvas && ctx) fillWhite(ctx, canvas.width, canvas.height);
      remoteState.last = null;
    };

    const onDraw = (payload: unknown) => {
      const packet = decodeLiveDrawing(payload);
      if (!packet) return;
      historyRef.current.apply(packet);
      if (packet.event === "draw_start") onDrawStart(packet.payload);
      else if (packet.event === "draw_move") onDrawMove(packet.payload);
      else if (packet.event === "draw_end") onDrawEnd();
      else if (packet.event === "draw_shape") onDrawShape(packet.payload);
      else if (packet.event === "draw_fill") onDrawFill(packet.payload);
      else onClearCanvas();
    };

    const replayActions = (actions: DecodedCanvasAction[]) => {
      const replayGeneration = ++replayGenerationRef.current;
      // Replay the entire stroke log into an offscreen buffer first, then
      // swap it onto the visible canvas in a single paint. Replaying
      // directly on the visible canvas would expose a blank/partial frame
      // during a full replay, most noticeably after Undo.
      const offscreen = document.createElement("canvas");
      offscreen.width = CANVAS_WIDTH;
      offscreen.height = CANVAS_HEIGHT;
      const offCtx = offscreen.getContext("2d", { willReadFrequently: true });
      if (!offCtx) return;
      fillWhite(offCtx, CANVAS_WIDTH, CANVAS_HEIGHT);

      for (const action of actions) {
        if (action.kind === "path") {
          if (action.points.length > 0) {
            rasterizePath(
              offCtx,
              action.points.length === 1
                ? [action.points[0], action.points[0]]
                : action.points,
              action.width / 2,
              hexToRgba(action.color),
              false,
            );
          }
        } else if (action.kind === "shape") {
          drawShapeOn(offCtx, action.payload);
        } else if (action.kind === "fill") {
          applyFillAtPixel(offCtx, action.x, action.y, action.color);
        } else {
          fillWhite(offCtx, CANVAS_WIDTH, CANVAS_HEIGHT);
        }
      }

      const canvas = canvasRef.current;
      const ctx = ctxRef.current;
      if (replayGeneration === replayGenerationRef.current && canvas && ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(offscreen, 0, 0);
      }
      remoteState.last = null;
    };

    const onSyncStrokes = (
      payload: unknown,
      revision: unknown,
      generation: unknown,
      sequence: unknown,
      historyHash: unknown,
    ) => {
      const actions = decodeCanvasHistory(payload);
      if (
        !actions
        || !historyRef.current.replace(
          actions,
          revision,
          generation,
          sequence,
          historyHash,
        )
      ) {
        requestAuthoritativeSync();
        return;
      }
      activeOutgoingSequenceRef.current = null;
      const committedGeneration = historyRef.current.generation!;
      const committedSequence = historyRef.current.sequence!;
      if (
        [...pendingMutationsRef.current.values()].some(
          (pending) => pending.generation !== committedGeneration,
        )
      ) {
        pendingMutationsRef.current.clear();
        nextSequenceRef.current = committedSequence + 1;
        replayActions(actions);
        return;
      }
      for (const pendingSequence of pendingMutationsRef.current.keys()) {
        if (pendingSequence <= committedSequence) {
          pendingMutationsRef.current.delete(pendingSequence);
        }
      }
      const pendingSequences = [...pendingMutationsRef.current.keys()]
        .sort((left, right) => left - right);
      if (
        pendingSequences.some(
          (pendingSequence, index) =>
            pendingSequence !== committedSequence + index + 1,
        )
      ) {
        pendingMutationsRef.current.clear();
        nextSequenceRef.current = committedSequence + 1;
        replayActions(actions);
        return;
      }

      let recoveryValid = true;
      for (const pendingSequence of pendingSequences) {
        const pending = pendingMutationsRef.current.get(pendingSequence)!;
        if (pending.kind === "draw") {
          let isIncompletePath = false;
          for (const frame of pending.frames) {
            const packet = decodeLiveDrawing(frame);
            if (!packet || !historyRef.current.apply(packet)) {
              recoveryValid = false;
              break;
            }
            isIncompletePath = (
              pending.frames.length > 0
              && decodeLiveDrawing(pending.frames[0])?.event === "draw_start"
              && packet.event !== "draw_end"
            );
          }
          if (!recoveryValid) break;
          pending.expectedRevision = isIncompletePath
            ? null
            : historyRef.current.revision;
          pending.expectedHash = isIncompletePath
            ? null
            : historyRef.current.historyHash;
          if (isIncompletePath) {
            activeOutgoingSequenceRef.current = pendingSequence;
          }
          pending.frames.forEach((frame, index) => {
            socket.emit(
              "draw",
              frame,
              index === 0
                ? [pending.generation, pendingSequence]
                : undefined,
            );
          });
        } else {
          const request = historyRef.current.prepareUndo(pendingSequence);
          if (!request) {
            recoveryValid = false;
            break;
          }
          pending.request = request;
          pending.expectedRevision = historyRef.current.revision!;
          pending.expectedHash = historyRef.current.historyHash!;
          socket.emit("undo_stroke", request);
        }
      }
      if (!recoveryValid) {
        pendingMutationsRef.current.clear();
        historyRef.current.replace(
          actions,
          revision,
          generation,
          sequence,
          historyHash,
        );
        nextSequenceRef.current = committedSequence + 1;
        replayActions(actions);
        return;
      }
      nextSequenceRef.current = (
        pendingSequences.at(-1) ?? committedSequence
      ) + 1;
      replayActions(historyRef.current.actions);
    };

    const onCanvasCommit = (payload: unknown) => {
      const sequence = Array.isArray(payload) ? payload[1] : null;
      const pending = typeof sequence === "number"
        ? pendingMutationsRef.current.get(sequence)
        : undefined;
      const valid = pending?.kind === "draw"
        ? historyRef.current.confirmAction(
          payload,
          pending.expectedRevision,
          pending.expectedHash,
        )
        : historyRef.current.confirmAction(payload);
      if (!valid) {
        requestAuthoritativeSync();
        return;
      }
      pendingMutationsRef.current.delete(sequence);
    };

    const onUndoStroke = (payload: unknown) => {
      const sequence = Array.isArray(payload) ? payload[1] : null;
      const pending = typeof sequence === "number"
        ? pendingMutationsRef.current.get(sequence)
        : undefined;
      const valid = pending?.kind === "undo"
        ? historyRef.current.confirmUndo(
          payload,
          pending.expectedRevision,
          pending.expectedHash,
        )
        : historyRef.current.confirmUndo(payload);
      if (!valid) {
        requestAuthoritativeSync();
        return;
      }
      pendingMutationsRef.current.delete(sequence);
      replayActions(historyRef.current.actions);
    };

    const onRequestCanvasActions = (payload: unknown) => {
      if (
        !Array.isArray(payload)
        || payload.length !== 3
        || !Number.isSafeInteger(payload[0])
        || !Number.isSafeInteger(payload[1])
        || !Number.isSafeInteger(payload[2])
        || payload[0] !== historyRef.current.generation
      ) {
        requestAuthoritativeSync();
        return;
      }
      for (let sequence = payload[1]; sequence <= payload[2]; sequence++) {
        const pending = pendingMutationsRef.current.get(sequence);
        if (!pending) {
          requestAuthoritativeSync();
          return;
        }
        if (pending.kind === "undo") {
          socket.emit("undo_stroke", pending.request);
          continue;
        }
        pending.frames.forEach((frame, index) => {
          socket.emit(
            "draw",
            frame,
            index === 0 ? [pending.generation, sequence] : undefined,
          );
        });
      }
    };

    const onCanvasReset = (payload: unknown) => {
      if (!historyRef.current.reset(payload)) {
        requestAuthoritativeSync();
        return;
      }
      pendingMutationsRef.current.clear();
      activeOutgoingSequenceRef.current = null;
      nextSequenceRef.current = 1;
      onClearCanvas();
    };

    const requestUndo = () => {
      finalizeActivePath();
      const sequence = allocateSequence();
      if (sequence === null) return;
      const request = historyRef.current.prepareUndo(sequence);
      if (!request) {
        nextSequenceRef.current -= 1;
        return;
      }
      pendingMutationsRef.current.set(sequence, {
        kind: "undo",
        generation: request[0],
        request,
        expectedRevision: historyRef.current.revision!,
        expectedHash: historyRef.current.historyHash!,
      });
      replayActions(historyRef.current.actions);
      void emitWithAck<{ ok: boolean; error?: string }>("undo_stroke", request)
        .then((response) => {
          if (!response?.ok && response?.error !== "Drawing actions are out of sequence") {
            requestAuthoritativeSync();
          }
        })
        .catch(() => requestAuthoritativeSync(false));
    };

    const requestClear = () => {
      finalizeActivePath();
      if (!historyRef.current.apply({ event: "clear_canvas", payload: {} })) return;
      onClearCanvas();
      beginDrawAction(encodeClear());
    };

    socket.on("draw", onDraw);
    socket.on("sync_strokes", onSyncStrokes);
    socket.on("canvas_commit", onCanvasCommit);
    socket.on("canvas_undo", onUndoStroke);
    socket.on("request_canvas_actions", onRequestCanvasActions);
    socket.on("canvas_reset", onCanvasReset);
    registerCanvasCommandHandlers({ clear: requestClear, undo: requestUndo });
    socket.emit("request_sync_strokes");

    return () => {
      socket.off("draw", onDraw);
      socket.off("sync_strokes", onSyncStrokes);
      socket.off("canvas_commit", onCanvasCommit);
      socket.off("canvas_undo", onUndoStroke);
      socket.off("request_canvas_actions", onRequestCanvasActions);
      socket.off("canvas_reset", onCanvasReset);
      registerCanvasCommandHandlers(null);
    };
  }, [
    allocateSequence,
    beginDrawAction,
    finalizeActivePath,
    requestAuthoritativeSync,
  ]);

  function getNormalizedPoint(e: ReactPointerEvent<HTMLCanvasElement>): StrokePoint {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.round(
        ((e.clientX - rect.left) / rect.width)
          * CANVAS_WIDTH
          * CANVAS_COORDINATE_SCALE,
      ) / (CANVAS_WIDTH * CANVAS_COORDINATE_SCALE),
      y: Math.round(
        ((e.clientY - rect.top) / rect.height)
          * CANVAS_HEIGHT
          * CANVAS_COORDINATE_SCALE,
      ) / (CANVAS_HEIGHT * CANVAS_COORDINATE_SCALE),
    };
  }

  const activeColor = tool === "eraser" ? "#ffffff" : color;

  function drawLocalSegment(from: StrokePoint, to: StrokePoint) {
    const ctx = ctxRef.current;
    if (!ctx) return;
    rasterizePath(ctx, [toPixels(from), toPixels(to)], brushWidth / 2, hexToRgba(activeColor), false);
  }

  function clearPreview() {
    const preview = previewCanvasRef.current;
    const previewCtx = previewCtxRef.current;
    if (preview && previewCtx) previewCtx.clearRect(0, 0, preview.width, preview.height);
  }

  // Flood-fills locally, then sends only the semantic action. Other clients
  // and replay rebuild the result from the same point and color.
  function performFill(point: StrokePoint) {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const payload: StrokeFillPayload = { x: point.x, y: point.y, color };
    if (applyFillAction(ctx, payload)) {
      historyRef.current.apply({ event: "draw_fill", payload });
      beginDrawAction(encodeFill(payload));
    }
  }

  function handlePointerDown(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (!isDrawer) return;

    // Ignore secondary pointers (e.g. 2nd finger in multi-touch / pinch gestures)
    if (!e.isPrimary) {
      if (isPointerDownRef.current) {
        handlePointerUp();
      }
      return;
    }

    if (activePointerIdRef.current !== null && activePointerIdRef.current !== e.pointerId) {
      if (isPointerDownRef.current) {
        handlePointerUp();
      }
      activePointerIdRef.current = null;
      return;
    }

    activePointerIdRef.current = e.pointerId;
    e.currentTarget.setPointerCapture(e.pointerId);

    const point = getNormalizedPoint(e);
    pointerPosRef.current = point;
    const showCirclePreview = tool === "eraser" || (tool === "pen" && penCursor === "circle");
    if (showCirclePreview) {
      clearPreview();
      drawCircleCursorPreview(point, brushWidth);
    }
    isPointerDownRef.current = true;
    lastPointRef.current = point;
    if (tool === "pen" || tool === "eraser") {
      drawLocalSegment(point, point); // visible dot for a single click/tap
      historyRef.current.apply({
        event: "draw_start",
        payload: {
          x: point.x,
          y: point.y,
          color: activeColor,
          width: brushWidth,
        },
      });
      beginDrawAction(
        encodePathStart({
          x: point.x,
          y: point.y,
          color: activeColor,
          width: brushWidth,
        }),
        true,
      );
    } else if (tool === "fill") {
      performFill(point);
    } else {
      shapeStartRef.current = point;
    }
  }

  const pointerPosRef = useRef<StrokePoint | null>(null);
  const penCursor = useSettingsStore((s) => s.penCursor);

  function drawCircleCursorPreview(point: StrokePoint, width: number) {
    const previewCtx = previewCtxRef.current;
    if (!previewCtx) return;
    const px = toPixels(point);
    const radius = width / 2;
    previewCtx.save();
    previewCtx.beginPath();
    previewCtx.arc(px.x, px.y, Math.max(radius, 1.5), 0, Math.PI * 2);
    previewCtx.strokeStyle = "rgba(0, 0, 0, 0.75)";
    previewCtx.lineWidth = 1.5;
    previewCtx.stroke();
    previewCtx.beginPath();
    previewCtx.arc(px.x, px.y, Math.max(radius, 1.5), 0, Math.PI * 2);
    previewCtx.strokeStyle = "rgba(255, 255, 255, 0.9)";
    previewCtx.lineWidth = 0.8;
    previewCtx.stroke();
    previewCtx.restore();
  }

  // Clear preview canvas and re-render cursor outline when brushWidth, tool, penCursor, or drawer status changes
  useEffect(() => {
    const showCirclePreview = isDrawer && (tool === "eraser" || (tool === "pen" && penCursor === "circle"));
    clearPreview();
    if (showCirclePreview && pointerPosRef.current) {
      drawCircleCursorPreview(pointerPosRef.current, brushWidth);
    }
  }, [brushWidth, tool, isDrawer, penCursor]);

  function handlePointerMove(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (!isDrawer) return;

    if (!e.isPrimary || (activePointerIdRef.current !== null && e.pointerId !== activePointerIdRef.current)) {
      return;
    }

    const point = getNormalizedPoint(e);
    pointerPosRef.current = point;

    const showCirclePreview = tool === "eraser" || (tool === "pen" && penCursor === "circle");

    if (showCirclePreview) {
      clearPreview();
      drawCircleCursorPreview(point, brushWidth);
    }

    if (!isPointerDownRef.current) return;
    if (tool === "fill") return; // fill happens once on pointer-down, not a drag

    if (tool === "pen" || tool === "eraser") {
      if (lastPointRef.current) drawLocalSegment(lastPointRef.current, point);
      lastPointRef.current = point;
      pendingPointsRef.current.push(point);
      historyRef.current.apply({
        event: "draw_move",
        payload: { points: [point] },
      });
    } else {
      lastPointRef.current = point;
      const previewCtx = previewCtxRef.current;
      const start = shapeStartRef.current;
      if (previewCtx && start) {
        clearPreview();
        drawShapeOutline(previewCtx, start, point, tool, color, brushWidth);
      }
    }
  }

  function handlePointerUp(e?: ReactPointerEvent<HTMLCanvasElement>) {
    if (!isDrawer) return;
    if (e && activePointerIdRef.current !== null && e.pointerId !== activePointerIdRef.current) {
      return;
    }
    activePointerIdRef.current = null;
    isPointerDownRef.current = false;
    if (tool === "fill") {
      lastPointRef.current = null;
      return;
    }
    if (tool === "pen" || tool === "eraser") {
      lastPointRef.current = null;
      if (pendingPointsRef.current.length > 0) {
        sendPathFrame(encodePathPoints({ points: pendingPointsRef.current }));
        pendingPointsRef.current = [];
      }
      historyRef.current.apply({ event: "draw_end", payload: {} });
      sendPathFrame(encodePathEnd());
      finishPathAction();
    } else {
      const start = shapeStartRef.current;
      const end = lastPointRef.current;
      clearPreview();
      if (start && end && (tool === "rectangle" || tool === "ellipse" || tool === "triangle")) {
        const ctx = ctxRef.current;
        if (ctx) {
          drawShapeOutlinePixels(ctx, start, end, tool, color, brushWidth);
        }
        historyRef.current.apply({
          event: "draw_shape",
          payload: {
            shape: tool,
            from: start,
            to: end,
            color,
            width: brushWidth,
          },
        });
        beginDrawAction(
          encodeShape({
            shape: tool,
            from: start,
            to: end,
            color,
            width: brushWidth,
          }),
        );
      }
      shapeStartRef.current = null;
      lastPointRef.current = null;
    }
  }

  function handlePointerLeave(e?: ReactPointerEvent<HTMLCanvasElement>) {
    pointerPosRef.current = null;
    clearPreview();
    if (isPointerDownRef.current) {
      handlePointerUp(e);
    }
  }

  function handlePointerCancel(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (activePointerIdRef.current === e.pointerId || !e.isPrimary) {
      pointerPosRef.current = null;
      clearPreview();
      handlePointerUp(e);
    }
  }

  function handleSaveImage() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dataUrl = canvas.toDataURL("image/png");
    const link = document.createElement("a");
    const dateStr = getYYMMDDhhmm();
    const promptSlug = solutionWord ? sanitizePrompt(solutionWord) : "";
    const suffix = promptSlug ? `-${promptSlug}` : "";
    link.download = `sketchy-${dateStr}${suffix}.png`;
    link.href = dataUrl;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  return (
    <div className="canvas-wrapper">
      <div className="canvas-stack">
        <canvas
          ref={canvasRef}
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
          className={`drawing-canvas${isDrawer ? " drawable" : ""}${isDrawer && (tool === "eraser" || (tool === "pen" && penCursor === "circle")) ? " eraser-tool" : ""}`}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerLeave}
          onPointerCancel={handlePointerCancel}
        />
        <canvas
          ref={previewCanvasRef}
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
          className="preview-canvas"
        />
        {overlay}
      </div>
    </div>
  );
});
