import { useEffect, useRef } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { socket } from "../lib/socket";
import type {
  DrawTool,
  ShapeType,
  StrokeFillPayload,
  StrokeMovePayload,
  StrokePoint,
  StrokeRecord,
  StrokeShapePayload,
  StrokeStartPayload,
} from "../types";

const CANVAS_WIDTH = 800;
const CANVAS_HEIGHT = 600;
const FLUSH_INTERVAL_MS = 40;

interface CanvasProps {
  isDrawer: boolean;
  color: string;
  brushWidth: number;
  tool: DrawTool;
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
// a white stroke over blank canvas would snap to opaque white pixel data
// sitting right next to transparent "blank" pixels - an invisible boundary
// to the eye, but a very real one to flood fill (and to hard-edge draws
// generally), which would then refuse to flow across it. Painting the
// canvas with actual opaque white up front - and every time it's cleared -
// keeps the underlying pixel data consistent with what's visible, so a
// white stroke is indistinguishable from blank canvas everywhere it matters.
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

interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function boundsFromPoints(a: { x: number; y: number }, b: { x: number; y: number }, strokeWidth: number): Bounds {
  // Pad by half the stroke width plus a couple pixels of slack for round
  // caps/joins and any incidental anti-aliasing spread beyond the nominal
  // width, so the snapshot fully covers everything this stroke could touch.
  const pad = strokeWidth / 2 + 2;
  return {
    minX: Math.min(a.x, b.x) - pad,
    minY: Math.min(a.y, b.y) - pad,
    maxX: Math.max(a.x, b.x) + pad,
    maxY: Math.max(a.y, b.y) + pad,
  };
}

// Canvas 2D has no way to disable anti-aliasing on stroked/filled paths
// (unlike `imageSmoothingEnabled`, which only applies to drawImage), so every
// stroke/shape edge would otherwise leave a fringe of partially-blended
// pixels that are neither the drawn color nor the prior background - making
// exact-match flood fill unreliable, and any tolerance/dilation-based
// workaround compounds worse with every repeated fill of the same region
// (each pass eats a little more of the fringe, so the "filled" area visibly
// grows on each click). Instead, every draw call is wrapped in this helper,
// which snapshots the affected region before drawing, then snaps every pixel
// touched by the draw call to EXACTLY the drawn color or EXACTLY its prior
// value - whichever it ended up closer to - so the canvas only ever contains
// flat, exactly-matchable colors and flood fill can rely on cheap equality
// with zero drift across repeated fills.
function drawWithHardEdges(
  ctx: CanvasRenderingContext2D,
  bounds: Bounds,
  drawColor: [number, number, number, number],
  draw: () => void,
): void {
  const x = Math.max(0, Math.floor(bounds.minX));
  const y = Math.max(0, Math.floor(bounds.minY));
  const right = Math.min(CANVAS_WIDTH, Math.ceil(bounds.maxX));
  const bottom = Math.min(CANVAS_HEIGHT, Math.ceil(bounds.maxY));
  const w = right - x;
  const h = bottom - y;
  if (w <= 0 || h <= 0) {
    draw();
    return;
  }

  const before = ctx.getImageData(x, y, w, h);
  draw();
  const after = ctx.getImageData(x, y, w, h);
  const beforeData = before.data;
  const afterData = after.data;

  for (let i = 0; i < afterData.length; i += 4) {
    if (
      afterData[i] === beforeData[i] &&
      afterData[i + 1] === beforeData[i + 1] &&
      afterData[i + 2] === beforeData[i + 2] &&
      afterData[i + 3] === beforeData[i + 3]
    ) {
      continue; // untouched by this draw call
    }
    const dr1 = afterData[i] - drawColor[0];
    const dg1 = afterData[i + 1] - drawColor[1];
    const db1 = afterData[i + 2] - drawColor[2];
    const da1 = afterData[i + 3] - drawColor[3];
    const distToDrawColor = dr1 * dr1 + dg1 * dg1 + db1 * db1 + da1 * da1;

    const dr2 = afterData[i] - beforeData[i];
    const dg2 = afterData[i + 1] - beforeData[i + 1];
    const db2 = afterData[i + 2] - beforeData[i + 2];
    const da2 = afterData[i + 3] - beforeData[i + 3];
    const distToBefore = dr2 * dr2 + dg2 * dg2 + db2 * db2 + da2 * da2;

    if (distToDrawColor <= distToBefore) {
      afterData[i] = drawColor[0];
      afterData[i + 1] = drawColor[1];
      afterData[i + 2] = drawColor[2];
      afterData[i + 3] = drawColor[3];
    } else {
      afterData[i] = beforeData[i];
      afterData[i + 1] = beforeData[i + 1];
      afterData[i + 2] = beforeData[i + 2];
      afterData[i + 3] = beforeData[i + 3];
    }
  }
  ctx.putImageData(after, x, y);
}

interface BoundingBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

// Stack-based 4-connected flood fill, mutating `imageData.data` in place and
// returning the bounding box of every pixel it touched (or null if the
// clicked pixel already exactly matches the fill color). Since every stroke
// is drawn via drawWithHardEdges, the canvas only ever contains flat colors,
// so exact equality is all that's needed - no tolerance, no dilation, no
// drift on repeated fills. Matching is purely pixel-based, so it naturally
// respects whatever shape the rendered strokes happen to form - including
// sub-regions carved out by self-intersecting lines, which have no explicit
// notion of "closed path" on a raster canvas.
function floodFillPixels(
  imageData: ImageData,
  startX: number,
  startY: number,
  fillColor: [number, number, number, number],
): BoundingBox | null {
  const { width, height, data } = imageData;
  const startIndex = (startY * width + startX) * 4;
  if (colorsEqual(data, startIndex, fillColor)) return null;
  const target: [number, number, number, number] = [
    data[startIndex],
    data[startIndex + 1],
    data[startIndex + 2],
    data[startIndex + 3],
  ];

  const visited = new Uint8Array(width * height);
  const stack: number[] = [startX, startY];
  const box: BoundingBox = { minX: startX, minY: startY, maxX: startX, maxY: startY };

  while (stack.length > 0) {
    const y = stack.pop()!;
    const x = stack.pop()!;
    if (x < 0 || x >= width || y < 0 || y >= height) continue;
    const pixelIndex = y * width + x;
    if (visited[pixelIndex]) continue;
    const index = pixelIndex * 4;
    if (!colorsEqual(data, index, target)) continue;
    visited[pixelIndex] = 1;
    data[index] = fillColor[0];
    data[index + 1] = fillColor[1];
    data[index + 2] = fillColor[2];
    data[index + 3] = fillColor[3];
    if (x < box.minX) box.minX = x;
    if (x > box.maxX) box.maxX = x;
    if (y < box.minY) box.minY = y;
    if (y > box.maxY) box.maxY = y;
    stack.push(x + 1, y, x - 1, y, x, y + 1, x, y - 1);
  }
  return box;
}

// Loads a data-URL image (never a network fetch, so this resolves quickly),
// used so replay (sync_strokes) can await each fill patch in order before
// applying subsequent strokes on top of it.
function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("failed to load fill patch image"));
    img.src = src;
  });
}

async function applyFillPatch(ctx: CanvasRenderingContext2D, payload: StrokeFillPayload): Promise<void> {
  try {
    const img = await loadImage(`data:image/png;base64,${payload.patchData}`);
    ctx.drawImage(img, payload.patchX, payload.patchY);
  } catch {
    // A corrupt/undecodable patch shouldn't crash the whole replay - just skip it.
  }
}

export function Canvas({ isDrawer, color, brushWidth, tool }: CanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);
  const previewCtxRef = useRef<CanvasRenderingContext2D | null>(null);
  const isPointerDownRef = useRef(false);
  const pendingPointsRef = useRef<StrokePoint[]>([]);
  const lastPointRef = useRef<StrokePoint | null>(null);
  const shapeStartRef = useRef<StrokePoint | null>(null);

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
    isPointerDownRef.current = false;
    pendingPointsRef.current = [];
    lastPointRef.current = null;
    shapeStartRef.current = null;
    const preview = previewCanvasRef.current;
    const previewCtx = previewCtxRef.current;
    if (preview && previewCtx) previewCtx.clearRect(0, 0, preview.width, preview.height);
  }, [isDrawer]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
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
      socket.emit("draw_move", { points });
    }, FLUSH_INTERVAL_MS);
    return () => clearInterval(flushTimer);
  }, []);

  // Render strokes coming from the current drawer (remote to this client).
  useEffect(() => {
    function drawSegmentOn(
      ctx: CanvasRenderingContext2D,
      from: StrokePoint,
      to: StrokePoint,
      strokeColor: string,
      strokeWidth: number,
    ) {
      const a = toPixels(from);
      const b = toPixels(to);
      drawWithHardEdges(ctx, boundsFromPoints(a, b, strokeWidth), hexToRgba(strokeColor), () => {
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = strokeWidth;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      });
    }

    function drawShapeOn(ctx: CanvasRenderingContext2D, payload: StrokeShapePayload) {
      const a = toPixels(payload.from);
      const b = toPixels(payload.to);
      drawWithHardEdges(ctx, boundsFromPoints(a, b, payload.width), hexToRgba(payload.color), () => {
        drawShapeOutline(ctx, payload.from, payload.to, payload.shape, payload.color, payload.width);
      });
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
      for (const point of payload.points) {
        if (remoteState.last) {
          drawSegment(remoteState.last, point, remoteState.color, remoteState.width);
        }
        remoteState.last = point;
      }
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
      void applyFillPatch(ctx, payload);
    };

    const onClearCanvas = () => {
      const canvas = canvasRef.current;
      const ctx = ctxRef.current;
      if (canvas && ctx) fillWhite(ctx, canvas.width, canvas.height);
      remoteState.last = null;
    };

    const onSyncStrokes = async (payload: { strokes: StrokeRecord[] }) => {
      // Replay the entire stroke log into an offscreen buffer first, then
      // swap it onto the visible canvas in a single paint. Replaying
      // directly on the visible canvas (as before) meant clearing it up
      // front and redrawing stroke-by-stroke while awaiting each fill
      // patch's async image decode in between - which left the canvas
      // visibly blank/partial for a frame or more whenever the log
      // contained a fill, producing a flicker (most noticeable right after
      // Undo, since undo always triggers a full resync).
      const offscreen = document.createElement("canvas");
      offscreen.width = CANVAS_WIDTH;
      offscreen.height = CANVAS_HEIGHT;
      const offCtx = offscreen.getContext("2d");
      if (!offCtx) return;
      fillWhite(offCtx, CANVAS_WIDTH, CANVAS_HEIGHT);

      let last: StrokePoint | null = null;
      let color = "#000000";
      let width = 4;

      for (const stroke of payload.strokes) {
        if (stroke.event === "draw_start") {
          const p = stroke.payload as StrokeStartPayload;
          last = { x: p.x, y: p.y };
          color = p.color;
          width = p.width;
          drawSegmentOn(offCtx, last, last, color, width);
        } else if (stroke.event === "draw_move") {
          const p = stroke.payload as StrokeMovePayload;
          for (const point of p.points) {
            if (last) drawSegmentOn(offCtx, last, point, color, width);
            last = point;
          }
        } else if (stroke.event === "draw_shape") {
          drawShapeOn(offCtx, stroke.payload as StrokeShapePayload);
        } else if (stroke.event === "draw_fill") {
          await applyFillPatch(offCtx, stroke.payload as StrokeFillPayload);
        } else {
          last = null;
        }
      }

      const canvas = canvasRef.current;
      const ctx = ctxRef.current;
      if (canvas && ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(offscreen, 0, 0);
      }
      remoteState.last = null;
    };

    socket.on("draw_start", onDrawStart);
    socket.on("draw_move", onDrawMove);
    socket.on("draw_end", onDrawEnd);
    socket.on("draw_shape", onDrawShape);
    socket.on("draw_fill", onDrawFill);
    socket.on("clear_canvas", onClearCanvas);
    socket.on("sync_strokes", onSyncStrokes);

    return () => {
      socket.off("draw_start", onDrawStart);
      socket.off("draw_move", onDrawMove);
      socket.off("draw_end", onDrawEnd);
      socket.off("draw_shape", onDrawShape);
      socket.off("draw_fill", onDrawFill);
      socket.off("clear_canvas", onClearCanvas);
      socket.off("sync_strokes", onSyncStrokes);
    };
  }, []);

  function getNormalizedPoint(e: ReactPointerEvent<HTMLCanvasElement>): StrokePoint {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    };
  }

  function drawLocalSegment(from: StrokePoint, to: StrokePoint) {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const a = { x: from.x * CANVAS_WIDTH, y: from.y * CANVAS_HEIGHT };
    const b = { x: to.x * CANVAS_WIDTH, y: to.y * CANVAS_HEIGHT };
    drawWithHardEdges(ctx, boundsFromPoints(a, b, brushWidth), hexToRgba(color), () => {
      ctx.strokeStyle = color;
      ctx.lineWidth = brushWidth;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    });
  }

  function clearPreview() {
    const preview = previewCanvasRef.current;
    const previewCtx = previewCtxRef.current;
    if (preview && previewCtx) previewCtx.clearRect(0, 0, preview.width, preview.height);
  }

  // Flood-fills starting at the clicked pixel, applies the result to the
  // local canvas immediately, and ships the affected rectangular patch as a
  // PNG so every other client renders pixel-identical results (see
  // StrokeFillPayload).
  function performFill(point: StrokePoint) {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const x = Math.floor(point.x * CANVAS_WIDTH);
    const y = Math.floor(point.y * CANVAS_HEIGHT);
    if (x < 0 || x >= CANVAS_WIDTH || y < 0 || y >= CANVAS_HEIGHT) return;

    const imageData = ctx.getImageData(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    const box = floodFillPixels(imageData, x, y, hexToRgba(color));
    if (!box) return; // clicked pixel already matches the fill color closely enough
    ctx.putImageData(imageData, 0, 0);

    const patchWidth = box.maxX - box.minX + 1;
    const patchHeight = box.maxY - box.minY + 1;
    const patchCanvas = document.createElement("canvas");
    patchCanvas.width = patchWidth;
    patchCanvas.height = patchHeight;
    const patchCtx = patchCanvas.getContext("2d");
    if (!patchCtx) return;
    patchCtx.putImageData(ctx.getImageData(box.minX, box.minY, patchWidth, patchHeight), 0, 0);
    const patchData = patchCanvas.toDataURL("image/png").split(",")[1] ?? "";

    socket.emit("draw_fill", {
      patchX: box.minX,
      patchY: box.minY,
      patchWidth,
      patchHeight,
      patchData,
    });
  }

  function handlePointerDown(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (!isDrawer) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const point = getNormalizedPoint(e);
    isPointerDownRef.current = true;
    lastPointRef.current = point;
    if (tool === "pen") {
      drawLocalSegment(point, point); // visible dot for a single click/tap
      socket.emit("draw_start", { x: point.x, y: point.y, color, width: brushWidth });
    } else if (tool === "fill") {
      performFill(point);
    } else {
      shapeStartRef.current = point;
    }
  }

  function handlePointerMove(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (!isDrawer || !isPointerDownRef.current) return;
    if (tool === "fill") return; // fill happens once on pointer-down, not a drag
    const point = getNormalizedPoint(e);
    if (tool === "pen") {
      if (lastPointRef.current) drawLocalSegment(lastPointRef.current, point);
      lastPointRef.current = point;
      pendingPointsRef.current.push(point);
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

  function handlePointerUp() {
    if (!isDrawer) return;
    isPointerDownRef.current = false;
    if (tool === "fill") {
      lastPointRef.current = null;
      return;
    }
    if (tool === "pen") {
      lastPointRef.current = null;
      if (pendingPointsRef.current.length > 0) {
        socket.emit("draw_move", { points: pendingPointsRef.current });
        pendingPointsRef.current = [];
      }
      socket.emit("draw_end", {});
    } else {
      const start = shapeStartRef.current;
      const end = lastPointRef.current;
      clearPreview();
      if (start && end) {
        const ctx = ctxRef.current;
        if (ctx) {
          const a = toPixels(start);
          const b = toPixels(end);
          drawWithHardEdges(ctx, boundsFromPoints(a, b, brushWidth), hexToRgba(color), () => {
            drawShapeOutline(ctx, start, end, tool, color, brushWidth);
          });
        }
        socket.emit("draw_shape", { shape: tool, from: start, to: end, color, width: brushWidth });
      }
      shapeStartRef.current = null;
      lastPointRef.current = null;
    }
  }

  return (
    <div className="canvas-stack">
      <canvas
        ref={canvasRef}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
        className={`drawing-canvas${isDrawer ? " drawable" : ""}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      />
      <canvas
        ref={previewCanvasRef}
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
        className="preview-canvas"
      />
    </div>
  );
}

