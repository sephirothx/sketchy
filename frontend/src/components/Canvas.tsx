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
import { toPixels } from "../lib/canvasGeometry";
import { hexToRgba } from "../lib/canvasPixels";
import {
  applyFillAction,
  applyFillAtPixel,
  drawShapeOutline,
  drawShapeOutlinePixels,
  fillWhite,
  rasterizePath,
  rasterizePolyline,
} from "../lib/canvasRenderer";
import type { Point } from "../lib/canvasGeometry";
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
  snapshotActions?: DecodedCanvasAction[] | null;
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

export interface CanvasRef {
  saveImage: () => void;
}

export const Canvas = forwardRef<CanvasRef, CanvasProps>(function Canvas(
  {
    isDrawer,
    color,
    brushWidth,
    tool,
    solutionWord = null,
    overlay = null,
    snapshotActions = null,
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
  const syncInFlightRef = useRef(false);
  const syncQueuedRef = useRef(false);

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
    if (syncInFlightRef.current) {
      syncQueuedRef.current = true;
      return;
    }
    syncInFlightRef.current = true;
    syncQueuedRef.current = false;
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
      syncInFlightRef.current = false;
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
        if (syncQueuedRef.current) {
          syncQueuedRef.current = false;
          requestAuthoritativeSync();
        }
        return;
      }
      for (const pendingSequence of pendingMutationsRef.current.keys()) {
        if (pendingSequence <= committedSequence) {
          pendingMutationsRef.current.delete(pendingSequence);
        }
      }
      // Never retransmit in-progress paths after a full sync — under a slow
      // link that multiplies into thousands of draw_move frames.
      for (const [pendingSequence, pending] of [...pendingMutationsRef.current.entries()]) {
        if (pending.kind !== "draw") continue;
        const incomplete = (
          pending.frames.length > 0
          && decodeLiveDrawing(pending.frames[0])?.event === "draw_start"
          && decodeLiveDrawing(pending.frames.at(-1)!)?.event !== "draw_end"
        );
        if (incomplete) {
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
        if (syncQueuedRef.current) {
          syncQueuedRef.current = false;
          requestAuthoritativeSync();
        }
        return;
      }

      let recoveryValid = true;
      for (const pendingSequence of pendingSequences) {
        const pending = pendingMutationsRef.current.get(pendingSequence)!;
        if (pending.kind === "draw") {
          for (const frame of pending.frames) {
            const packet = decodeLiveDrawing(frame);
            if (!packet || !historyRef.current.apply(packet)) {
              recoveryValid = false;
              break;
            }
          }
          if (!recoveryValid) break;
          pending.expectedRevision = historyRef.current.revision;
          pending.expectedHash = historyRef.current.historyHash;
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
        if (syncQueuedRef.current) {
          syncQueuedRef.current = false;
          requestAuthoritativeSync();
        }
        return;
      }
      nextSequenceRef.current = (
        pendingSequences.at(-1) ?? committedSequence
      ) + 1;
      replayActions(historyRef.current.actions);
      if (syncQueuedRef.current) {
        syncQueuedRef.current = false;
        requestAuthoritativeSync();
      }
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
        const incomplete = (
          pending.frames.length > 0
          && decodeLiveDrawing(pending.frames[0])?.event === "draw_start"
          && decodeLiveDrawing(pending.frames.at(-1)!)?.event !== "draw_end"
        );
        // Incomplete paths are dropped rather than replayed point-by-point.
        if (incomplete) {
          pendingMutationsRef.current.delete(sequence);
          if (activeOutgoingSequenceRef.current === sequence) {
            activeOutgoingSequenceRef.current = null;
          }
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

    const isPaintingStroke = () => (
      isPointerDownRef.current || activeOutgoingSequenceRef.current !== null
    );

    const requestUndo = () => {
      // Ignore Undo/Clear while a stroke is in progress — avoids sequence races
      // on slow links without needing a cancel-draw protocol.
      if (isPaintingStroke()) return;
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
      if (isPaintingStroke()) return;
      if (!historyRef.current.apply({ event: "clear_canvas", payload: {} })) return;
      onClearCanvas();
      beginDrawAction(encodeClear());
    };

    if (snapshotActions) {
      replayActions(snapshotActions);
      return () => {
        replayGenerationRef.current += 1;
      };
    }

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
    snapshotActions,
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
