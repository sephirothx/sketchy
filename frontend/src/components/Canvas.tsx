import { useEffect, useRef } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { socket } from "../lib/socket";
import type {
  DrawTool,
  ShapeType,
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

export function Canvas({ isDrawer, color, brushWidth, tool }: CanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);
  const previewCtxRef = useRef<CanvasRenderingContext2D | null>(null);
  const isPointerDownRef = useRef(false);
  const pendingPointsRef = useRef<StrokePoint[]>([]);
  const lastPointRef = useRef<StrokePoint | null>(null);
  const shapeStartRef = useRef<StrokePoint | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
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
    function drawSegment(from: StrokePoint, to: StrokePoint, strokeColor: string, strokeWidth: number) {
      const ctx = ctxRef.current;
      if (!ctx) return;
      const a = toPixels(from);
      const b = toPixels(to);
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = strokeWidth;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
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
      drawShapeOutline(ctx, payload.from, payload.to, payload.shape, payload.color, payload.width);
    };

    const onClearCanvas = () => {
      const canvas = canvasRef.current;
      const ctx = ctxRef.current;
      if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      remoteState.last = null;
    };

    const onSyncStrokes = (payload: { strokes: StrokeRecord[] }) => {
      onClearCanvas();
      for (const stroke of payload.strokes) {
        if (stroke.event === "draw_start") {
          onDrawStart(stroke.payload as StrokeStartPayload);
        } else if (stroke.event === "draw_move") {
          onDrawMove(stroke.payload as StrokeMovePayload);
        } else if (stroke.event === "draw_shape") {
          onDrawShape(stroke.payload as StrokeShapePayload);
        } else {
          onDrawEnd();
        }
      }
    };

    socket.on("draw_start", onDrawStart);
    socket.on("draw_move", onDrawMove);
    socket.on("draw_end", onDrawEnd);
    socket.on("draw_shape", onDrawShape);
    socket.on("clear_canvas", onClearCanvas);
    socket.on("sync_strokes", onSyncStrokes);

    return () => {
      socket.off("draw_start", onDrawStart);
      socket.off("draw_move", onDrawMove);
      socket.off("draw_end", onDrawEnd);
      socket.off("draw_shape", onDrawShape);
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
    ctx.strokeStyle = color;
    ctx.lineWidth = brushWidth;
    ctx.beginPath();
    ctx.moveTo(from.x * CANVAS_WIDTH, from.y * CANVAS_HEIGHT);
    ctx.lineTo(to.x * CANVAS_WIDTH, to.y * CANVAS_HEIGHT);
    ctx.stroke();
  }

  function clearPreview() {
    const preview = previewCanvasRef.current;
    const previewCtx = previewCtxRef.current;
    if (preview && previewCtx) previewCtx.clearRect(0, 0, preview.width, preview.height);
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
    } else {
      shapeStartRef.current = point;
    }
  }

  function handlePointerMove(e: ReactPointerEvent<HTMLCanvasElement>) {
    if (!isDrawer || !isPointerDownRef.current) return;
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
        if (ctx) drawShapeOutline(ctx, start, end, tool, color, brushWidth);
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

