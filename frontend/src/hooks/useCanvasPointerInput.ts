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
import { createPointThinner, type PointThinner } from "../lib/pointThinning";
import { useClientConfig } from "./useClientConfig";
import type { CanvasProtocol } from "./useCanvasProtocol";
import type { DrawTool, StrokeFillPayload, StrokePoint } from "../types";

interface DrawingSettings {
  isDrawer: boolean;
  color: string;
  brushWidth: number;
  tool: DrawTool;
  brushCursor: string;
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
    brushCursor,
  } = settings;
  // Painting locally past the point budget would put pixels on screen that
  // the server never accepted, and they would vanish at the next replay. Read
  // straight from the store: the handlers below are rebuilt every render, so
  // they always close over the current answer.
  const strokeAvailable = useCanvasBudgetStore((state) => state.strokeAvailable);
  // Server-decided, so a deployment can tune the trade between bandwidth and
  // how smooth a stroke looks to everyone who is not drawing it.
  const { flushIntervalMs } = useClientConfig();

  const activePointerIdRef = useRef<number | null>(null);
  const pendingPointsRef = useRef<StrokePoint[]>([]);
  // For a brush stroke, the last sample *kept* (#560), which is where the
  // next kept segment starts on this canvas and on every viewer's; for a
  // shape, the pointer's last position.
  const lastPointRef = useRef<StrokePoint | null>(null);
  // Thins the stroke under the pen; null between strokes.
  const thinnerRef = useRef<PointThinner | null>(null);
  // The last point the server has been sent for the open path - the start
  // point, then the last point of each frame - which the next frame's points
  // are encoded relative to (#559).
  const lastSentRef = useRef<StrokePoint | null>(null);
  const shapeStartRef = useRef<StrokePoint | null>(null);
  const pointerPosRef = useRef<StrokePoint | null>(null);
  const inputActiveRef = useRef(false);

  const showCircleCursor = isDrawer
    && (tool === "eraser" || (tool === "brush" && brushCursor === "circle"));

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

  // The preview layer, repainted as one picture: the circle cursor if there
  // is one, and the segment from the last kept sample to the one still
  // pending in the thinner, so the ink under the pen never lags a sample
  // behind what the drawer's hand did. Both go when the stroke ends.
  function repaintPreview(pointer: StrokePoint | null) {
    clearPreview();
    if (showCircleCursor && pointer) drawCircleCursorPreview(pointer, brushWidth);
    const thinner = thinnerRef.current;
    const pending = thinner?.pending();
    const previewContext = previewContextRef.current;
    if (!thinner || !pending || !previewContext) return;
    const activeColor = tool === "eraser" ? "#ffffff" : color;
    rasterizePath(
      previewContext,
      [toPixels(thinner.anchor()), toPixels(pending)],
      brushWidth / 2,
      hexToRgba(activeColor),
      false,
    );
  }

  // Samples the thinner kept: painted here from the last kept sample, and
  // queued for the frame, so the drawer's canvas and every viewer's are
  // rasterized from the same polyline (#560).
  function acceptPoints(points: StrokePoint[]) {
    for (const point of points) {
      if (lastPointRef.current) drawLocalSegment(lastPointRef.current, point);
      lastPointRef.current = point;
      pendingPointsRef.current.push(point);
    }
  }
  // The flush timer below is armed once and must paint with the colour and
  // width the stroke has *now*, not the ones it closed over when armed.
  const acceptRef = useRef(acceptPoints);
  const repaintPreviewRef = useRef(repaintPreview);
  useEffect(() => {
    acceptRef.current = acceptPoints;
    repaintPreviewRef.current = repaintPreview;
    sendPendingPointsRef.current = sendPendingPoints;
  });

  // The queued points as one frame, relative to the last point sent, which
  // they then become the last of - only if the frame went. A frame the
  // protocol dropped (over the point budget, no path open) left the server's
  // path where it was, and the next frame must be relative to that. With
  // `ends`, the frame also closes the path (#603). Returns whether it went.
  function sendPendingPoints(ends = false): boolean {
    const points = pendingPointsRef.current;
    if (points.length === 0) return false;
    pendingPointsRef.current = [];
    const previous = lastSentRef.current;
    if (ends && !previous) return false;
    const sent = protocol.sendPathFrame(
      encodePathPoints({ points, previous: previous ?? undefined, ...(ends ? { ends: true } : {}) }),
    );
    if (sent) lastSentRef.current = points[points.length - 1];
    return sent;
  }
  const sendPendingPointsRef = useRef(sendPendingPoints);

  // The points buffered when the pen lifted and the end go as one frame
  // (#603); the one-byte end alone when nothing is buffered, or when the
  // final batch did not go - a batch past the budget is refused whole, and
  // the stroke then ends where the budget ran out.
  function finishPath() {
    const thinner = thinnerRef.current;
    if (thinner) acceptPoints(thinner.end());
    thinnerRef.current = null;
    if (!sendPendingPoints(true)) protocol.sendPathFrame(encodePathEnd());
    lastSentRef.current = null;
    protocol.finishPathAction();
    repaintPreview(pointerPosRef.current);
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
    if (tool === "brush" || tool === "eraser") {
      // The stroke's last sample is kept here, and painted from the last
      // kept one - so that one is still needed.
      finishPath();
      lastPointRef.current = null;
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
    repaintPreview(point);
    if ((tool === "brush" || tool === "eraser") && !strokeAvailable) {
      activePointerIdRef.current = null;
      return;
    }
    inputActiveRef.current = true;
    lastPointRef.current = point;
    if (tool === "brush" || tool === "eraser") {
      const activeColor = tool === "eraser" ? "#ffffff" : color;
      thinnerRef.current = createPointThinner(point);
      lastSentRef.current = point;
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
    if (!inputActiveRef.current || tool === "fill") {
      repaintPreview(point);
      return;
    }
    if (tool === "brush" || tool === "eraser") {
      if (!strokeAvailable) {
        // The budget ran out under the brush. Close the stroke here so the
        // drawing stops in the same place on every screen.
        handlePointerUp(event);
        return;
      }
      const thinner = thinnerRef.current;
      if (thinner) acceptPoints(thinner.push(point));
      repaintPreview(point);
    } else {
      repaintPreview(point);
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
  //
  // The interval is in the dependency list rather than read inside the
  // callback, because `setInterval` fixes its period when it is armed: reading
  // a new value in the callback would change nothing until the timer was
  // recreated anyway. Listing it tears the timer down and re-arms it, so an
  // administrator moving the value reaches a drawer who is drawing right now
  // — which is the only way anyone can judge whether the new value is right.
  useEffect(() => {
    if (!isDrawer) return;
    const flushTimer = setInterval(() => {
      // The sample still pending in the thinner goes with this flush, so a
      // viewer watches a long straight stroke advance every flush rather
      // than only when it bends or ends (#560).
      const thinner = thinnerRef.current;
      if (thinner) {
        const forced = thinner.flush();
        if (forced.length > 0) {
          acceptRef.current(forced);
          repaintPreviewRef.current(pointerPosRef.current);
        }
      }
      sendPendingPointsRef.current();
    }, flushIntervalMs);
    return () => clearInterval(flushTimer);
  }, [isDrawer, protocol, flushIntervalMs]);

  useEffect(() => () => {
    if (!inputActiveRef.current) return;
    const thinner = thinnerRef.current;
    if (thinner) acceptRef.current(thinner.end());
    thinnerRef.current = null;
    if (!sendPendingPointsRef.current(true)) protocol.sendPathFrame(encodePathEnd());
    lastSentRef.current = null;
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
    thinnerRef.current = null;
    lastSentRef.current = null;
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
  }, [brushWidth, clearPreview, drawCircleCursorPreview, brushCursor, showCircleCursor, tool]);

  return {
    onPointerDown: handlePointerDown,
    onPointerMove: handlePointerMove,
    onPointerUp: handlePointerUp,
    onPointerLeave: handlePointerLeave,
    onPointerCancel: handlePointerCancel,
    showCircleCursor,
  };
}
