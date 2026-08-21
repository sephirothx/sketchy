import { useCallback, useEffect, useRef } from "react";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import {
  CANVAS_COORDINATE_SCALE,
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "../lib/canvasHistory";
import { toPixels } from "../lib/canvasGeometry";
import { registerCanvasCommandHandlers } from "../lib/canvasCommands";
import { hexToRgba } from "../lib/canvasPixels";
import {
  applyFillAction,
  drawShapeOutline,
  drawShapeOutlinePixels,
  rasterizePath,
} from "../lib/canvasRenderer";
import {
  encodeFill,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
  encodeShape,
} from "../lib/liveDrawing";
import type { CanvasProtocol } from "./useCanvasProtocol";
import type { DrawTool, StrokeFillPayload, StrokePoint } from "../types";

const FLUSH_INTERVAL_MS = 40;

interface DrawingSettings {
  isDrawer: boolean;
  color: string;
  brushWidth: number;
  tool: DrawTool;
  penCursor: string;
}

interface CanvasPointerInput {
  onPointerDown(event: ReactPointerEvent<HTMLCanvasElement>): void;
  onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>): void;
  onPointerUp(event?: ReactPointerEvent<HTMLCanvasElement>): void;
  onPointerLeave(event?: ReactPointerEvent<HTMLCanvasElement>): void;
  onPointerCancel(event: ReactPointerEvent<HTMLCanvasElement>): void;
  showCircleCursor: boolean;
}

export function useCanvasPointerInput(
  protocol: CanvasProtocol,
  canvasRef: RefObject<HTMLCanvasElement | null>,
  contextRef: RefObject<CanvasRenderingContext2D | null>,
  previewCanvasRef: RefObject<HTMLCanvasElement | null>,
  previewContextRef: RefObject<CanvasRenderingContext2D | null>,
  settings: DrawingSettings,
): CanvasPointerInput {
  const {
    isDrawer,
    color,
    brushWidth,
    tool,
    penCursor,
  } = settings;
  // Painting locally past the point budget would put pixels on screen that
  // the server never accepted, and they would vanish at the next replay. Read
  // straight from the store: the handlers below are rebuilt every render, so
  // they always close over the current answer.
  const strokeAvailable = useCanvasBudgetStore((state) => state.strokeAvailable);

  const activePointerIdRef = useRef<number | null>(null);
  const pendingPointsRef = useRef<StrokePoint[]>([]);
  const lastPointRef = useRef<StrokePoint | null>(null);
  const shapeStartRef = useRef<StrokePoint | null>(null);
  const pointerPosRef = useRef<StrokePoint | null>(null);
  const inputActiveRef = useRef(false);

  const showCircleCursor = isDrawer
    && (tool === "eraser" || (tool === "pen" && penCursor === "circle"));

  const clearPreview = useCallback(() => {
    const preview = previewCanvasRef.current;
    const previewContext = previewContextRef.current;
    if (preview && previewContext) {
      previewContext.clearRect(0, 0, preview.width, preview.height);
    }
  }, [previewCanvasRef, previewContextRef]);

  const drawCircleCursorPreview = useCallback((point: StrokePoint, width: number) => {
    const previewContext = previewContextRef.current;
    if (!previewContext) return;
    const pixels = toPixels(point);
    const radius = width / 2;
    previewContext.save();
    previewContext.beginPath();
    previewContext.arc(pixels.x, pixels.y, Math.max(radius, 1.5), 0, Math.PI * 2);
    previewContext.strokeStyle = "rgba(0, 0, 0, 0.75)";
    previewContext.lineWidth = 1.5;
    previewContext.stroke();
    previewContext.beginPath();
    previewContext.arc(pixels.x, pixels.y, Math.max(radius, 1.5), 0, Math.PI * 2);
    previewContext.strokeStyle = "rgba(255, 255, 255, 0.9)";
    previewContext.lineWidth = 0.8;
    previewContext.stroke();
    previewContext.restore();
  }, [previewContextRef]);

  function normalizedPoint(event: ReactPointerEvent<HTMLCanvasElement>): StrokePoint {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.round(
        ((event.clientX - rect.left) / rect.width)
          * CANVAS_WIDTH
          * CANVAS_COORDINATE_SCALE,
      ) / (CANVAS_WIDTH * CANVAS_COORDINATE_SCALE),
      y: Math.round(
        ((event.clientY - rect.top) / rect.height)
          * CANVAS_HEIGHT
          * CANVAS_COORDINATE_SCALE,
      ) / (CANVAS_HEIGHT * CANVAS_COORDINATE_SCALE),
    };
  }

  function drawLocalSegment(from: StrokePoint, to: StrokePoint) {
    const context = contextRef.current;
    if (!context) return;
    const activeColor = tool === "eraser" ? "#ffffff" : color;
    rasterizePath(
      context,
      [toPixels(from), toPixels(to)],
      brushWidth / 2,
      hexToRgba(activeColor),
      false,
    );
  }

  function finishPath() {
    if (pendingPointsRef.current.length > 0) {
      protocol.sendPathFrame(encodePathPoints({ points: pendingPointsRef.current }));
      pendingPointsRef.current = [];
    }
    protocol.sendPathFrame(encodePathEnd());
    protocol.finishPathAction();
  }

  function handlePointerUp(event?: ReactPointerEvent<HTMLCanvasElement>) {
    if (!isDrawer) return;
    if (
      event
      && activePointerIdRef.current !== null
      && event.pointerId !== activePointerIdRef.current
    ) return;
    activePointerIdRef.current = null;
    inputActiveRef.current = false;
    if (tool === "fill") {
      lastPointRef.current = null;
      return;
    }
    if (tool === "pen" || tool === "eraser") {
      lastPointRef.current = null;
      finishPath();
      return;
    }
    const start = shapeStartRef.current;
    const end = lastPointRef.current;
    clearPreview();
    if (start && end && (tool === "rectangle" || tool === "ellipse" || tool === "triangle")) {
      const context = contextRef.current;
      if (context) {
        drawShapeOutlinePixels(context, start, end, tool, color, brushWidth);
      }
      protocol.beginDrawAction(encodeShape({
        shape: tool,
        from: start,
        to: end,
        color,
        width: brushWidth,
      }));
    }
    shapeStartRef.current = null;
    lastPointRef.current = null;
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!isDrawer) return;
    if (!event.isPrimary) {
      if (inputActiveRef.current) handlePointerUp();
      return;
    }
    if (
      activePointerIdRef.current !== null
      && activePointerIdRef.current !== event.pointerId
    ) {
      if (inputActiveRef.current) handlePointerUp();
      activePointerIdRef.current = null;
      return;
    }
    activePointerIdRef.current = event.pointerId;
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = normalizedPoint(event);
    pointerPosRef.current = point;
    if (showCircleCursor) {
      clearPreview();
      drawCircleCursorPreview(point, brushWidth);
    }
    if ((tool === "pen" || tool === "eraser") && !strokeAvailable) {
      activePointerIdRef.current = null;
      return;
    }
    inputActiveRef.current = true;
    lastPointRef.current = point;
    if (tool === "pen" || tool === "eraser") {
      const activeColor = tool === "eraser" ? "#ffffff" : color;
      drawLocalSegment(point, point);
      protocol.beginDrawAction(encodePathStart({
        x: point.x,
        y: point.y,
        color: activeColor,
        width: brushWidth,
      }), true);
    } else if (tool === "fill") {
      const context = contextRef.current;
      const payload: StrokeFillPayload = { x: point.x, y: point.y, color };
      if (context && applyFillAction(context, payload)) {
        protocol.beginDrawAction(encodeFill(payload));
      }
    } else {
      shapeStartRef.current = point;
    }
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (
      !isDrawer
      || !event.isPrimary
      || (activePointerIdRef.current !== null
        && event.pointerId !== activePointerIdRef.current)
    ) return;
    const point = normalizedPoint(event);
    pointerPosRef.current = point;
    if (showCircleCursor) {
      clearPreview();
      drawCircleCursorPreview(point, brushWidth);
    }
    if (!inputActiveRef.current || tool === "fill") return;
    if (tool === "pen" || tool === "eraser") {
      if (!strokeAvailable) {
        // The budget ran out under the pen. Close the stroke here so the
        // drawing stops in the same place on every screen.
        handlePointerUp(event);
        return;
      }
      if (lastPointRef.current) drawLocalSegment(lastPointRef.current, point);
      lastPointRef.current = point;
      pendingPointsRef.current.push(point);
    } else {
      lastPointRef.current = point;
      const previewContext = previewContextRef.current;
      const start = shapeStartRef.current;
      if (previewContext && start) {
        clearPreview();
        drawShapeOutline(previewContext, start, point, tool, color, brushWidth);
      }
    }
  }

  function handlePointerLeave(event?: ReactPointerEvent<HTMLCanvasElement>) {
    pointerPosRef.current = null;
    clearPreview();
    if (inputActiveRef.current) handlePointerUp(event);
  }

  function handlePointerCancel(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (activePointerIdRef.current === event.pointerId || !event.isPrimary) {
      pointerPosRef.current = null;
      clearPreview();
      handlePointerUp(event);
    }
  }

  // Only the drawer ever queues points, so only the drawer needs the timer.
  // Guessers were waking a throttled CPU 25x a second to find nothing to send.
  useEffect(() => {
    if (!isDrawer) return;
    const flushTimer = setInterval(() => {
      if (pendingPointsRef.current.length === 0) return;
      const points = pendingPointsRef.current;
      pendingPointsRef.current = [];
      protocol.sendPathFrame(encodePathPoints({ points }));
    }, FLUSH_INTERVAL_MS);
    return () => clearInterval(flushTimer);
  }, [isDrawer, protocol]);

  useEffect(() => () => {
    if (!inputActiveRef.current) return;
    if (pendingPointsRef.current.length > 0) {
      protocol.sendPathFrame(encodePathPoints({ points: pendingPointsRef.current }));
      pendingPointsRef.current = [];
    }
    protocol.sendPathFrame(encodePathEnd());
    protocol.finishPathAction();
    inputActiveRef.current = false;
  }, [protocol]);

  useEffect(() => {
    registerCanvasCommandHandlers({
      clear: () => {
        if (!inputActiveRef.current) protocol.requestClear();
      },
      undo: () => {
        if (!inputActiveRef.current) protocol.requestUndo();
      },
    });
    return () => registerCanvasCommandHandlers(null);
  }, [protocol]);

  useEffect(() => {
    if (isDrawer) return;
    const hadActiveInput = inputActiveRef.current;
    activePointerIdRef.current = null;
    inputActiveRef.current = false;
    pendingPointsRef.current = [];
    lastPointRef.current = null;
    shapeStartRef.current = null;
    pointerPosRef.current = null;
    clearPreview();
    if (hadActiveInput) protocol.requestAuthoritativeSync();
  }, [clearPreview, isDrawer, protocol]);

  useEffect(() => {
    clearPreview();
    if (showCircleCursor && pointerPosRef.current) {
      drawCircleCursorPreview(pointerPosRef.current, brushWidth);
    }
  }, [brushWidth, clearPreview, drawCircleCursorPreview, penCursor, showCircleCursor, tool]);

  return {
    onPointerDown: handlePointerDown,
    onPointerMove: handlePointerMove,
    onPointerUp: handlePointerUp,
    onPointerLeave: handlePointerLeave,
    onPointerCancel: handlePointerCancel,
    showCircleCursor,
  };
}
