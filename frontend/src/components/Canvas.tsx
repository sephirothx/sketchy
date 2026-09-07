import {
  forwardRef,
  memo,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";
import type { ReactNode, RefObject } from "react";
import { useCanvasPointerInput } from "../hooks/useCanvasPointerInput";
import {
  useCanvasProtocol,
} from "../hooks/useCanvasProtocol";
import type { CanvasProtocolRenderer } from "../hooks/useCanvasProtocol";
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { toPixels } from "../lib/canvasGeometry";
import { hexToRgba } from "../lib/canvasPixels";
import {
  applyFillAction,
  drawShapeOutlinePixels,
  fillWhite,
  rasterizePolyline,
  renderCanvasActions,
} from "../lib/canvasRenderer";
import type { LiveDrawingPacket } from "../lib/liveDrawing";
import { currentClientConfig } from "../lib/clientConfig";
import { createStrokePlayback } from "../lib/strokePlayback";
import { useSettingsStore } from "../store/settingsStore";
import type { DrawTool, StrokePoint } from "../types";
import { saveCanvasImage } from "../lib/canvasDownload";
import { recordRender } from "../lib/renderDiagnostics";

interface CanvasProps {
  isDrawer: boolean;
  color: string;
  brushWidth: number;
  tool: DrawTool;
  downloadPrompt?: string | null;
  overlay?: ReactNode;
  label: string;
}

export interface CanvasRef {
  saveImage: () => void;
}

function createProtocolRenderer(
  canvasRef: RefObject<HTMLCanvasElement | null>,
  contextRef: RefObject<CanvasRenderingContext2D | null>,
): CanvasProtocolRenderer {
  let replayGeneration = 0;
  // One scratch canvas for the lifetime of the renderer. A replay used to
  // allocate a fresh 800x600 backing store (~1.9 MB) on every undo and sync;
  // renderCanvasActions overwrites every pixel, so nothing stale carries over.
  let scratch: HTMLCanvasElement | null = null;
  let scratchContext: CanvasRenderingContext2D | null = null;
  const remoteState: {
    last: StrokePoint | null;
    color: string;
    width: number;
  } = { last: null, color: "#000000", width: 4 };

  // Received points are played out over the flush interval that follows
  // them rather than painted the moment they land (#559): what is on screen
  // advances at the animation rate, while the history and the commits behind
  // it were applied synchronously by the protocol hook before `apply` was
  // called. Everything that is not a run of points is a barrier in the same
  // queue, so nothing is painted out of order.
  const playback = createStrokePlayback({
    intervalMs: () => currentClientConfig().flushIntervalMs,
    paint: (points, style) => {
      const context = contextRef.current;
      if (context) rasterizePolyline(context, points, style.radius, style.color);
    },
  });
  let frame: number | null = null;
  const tick = () => {
    frame = null;
    if (playback.advance(performance.now())) frame = window.requestAnimationFrame(tick);
  };
  const schedule = () => {
    if (frame === null && playback.pending()) frame = window.requestAnimationFrame(tick);
  };
  const stopTicking = () => {
    if (frame !== null) window.cancelAnimationFrame(frame);
    frame = null;
  };
  // A hidden tab gets no animation frames; drain rather than hold ink
  // for as long as it is away, so what it shows on return is current.
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") playback.drain();
    });
  }

  const clear = () => {
    replayGeneration += 1;
    playback.cancel();
    stopTicking();
    const canvas = canvasRef.current;
    const context = contextRef.current;
    if (canvas && context) fillWhite(context, canvas.width, canvas.height);
    remoteState.last = null;
  };

  const apply = (packet: LiveDrawingPacket) => {
    const context = contextRef.current;
    if (!context) return;
    const now = performance.now();
    if (packet.event === "draw_start") {
      const { x, y, color, width } = packet.payload;
      playback.enqueueBarrier(() => {
        remoteState.last = { x, y };
        remoteState.color = color;
        remoteState.width = width;
        const point = toPixels(remoteState.last);
        rasterizePolyline(context, [point, point], width / 2, hexToRgba(color));
      }, now);
    } else if (packet.event === "draw_move") {
      // `remoteState.last` is read when the batch is *queued*, not when it
      // is painted: the start barrier before it in the queue is what set it
      // - unless it ran already, in which case it is set already. Either
      // way the polyline joins the previous batch, so it is tracked here.
      if (packet.payload.points.length === 0) return;
      const from = remoteState.last ?? packet.payload.points[0];
      const style = { radius: remoteState.width / 2, color: hexToRgba(remoteState.color) };
      playback.enqueueSegments(
        toPixels(from),
        packet.payload.points.map(toPixels),
        style,
        now,
      );
      remoteState.last = packet.payload.points.at(-1)!;
    } else if (packet.event === "draw_end") {
      playback.enqueueBarrier(() => {
        remoteState.last = null;
      }, now);
    } else if (packet.event === "draw_shape") {
      const payload = packet.payload;
      playback.enqueueBarrier(() => {
        drawShapeOutlinePixels(
          context,
          payload.from,
          payload.to,
          payload.shape,
          payload.color,
          payload.width,
        );
      }, now);
    } else if (packet.event === "draw_fill") {
      // A fill must see the complete raster before it: a barrier, so every
      // queued point is painted first.
      const payload = packet.payload;
      playback.enqueueBarrier(() => {
        applyFillAction(context, payload);
      }, now);
    } else if (packet.event === "clear_canvas") {
      clear();
    }
    // `draw_move_relative` never reaches here: the protocol hook resolves it
    // against the history before it is painted (#559).
    schedule();
  };

  const replay = (actions: DecodedCanvasAction[]) => {
    const currentReplay = ++replayGeneration;
    // What was queued is inside the history being repainted, or superseded
    // by it; either way it must not land on top afterwards.
    playback.cancel();
    stopTicking();
    if (!scratch) {
      scratch = document.createElement("canvas");
      scratch.width = CANVAS_WIDTH;
      scratch.height = CANVAS_HEIGHT;
      scratchContext = scratch.getContext("2d", { willReadFrequently: true });
    }
    if (!scratchContext) return;
    renderCanvasActions(scratchContext, actions);
    const canvas = canvasRef.current;
    const context = contextRef.current;
    if (currentReplay === replayGeneration && canvas && context) {
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(scratch, 0, 0);
    }
    remoteState.last = null;
  };

  return { apply, clear, replay };
}

const CanvasComponent = forwardRef<CanvasRef, CanvasProps>(function Canvas(
  {
    isDrawer,
    color,
    brushWidth,
    tool,
    downloadPrompt = null,
    overlay = null,
    label,
  },
  ref,
) {
  recordRender("canvas");
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const contextRef = useRef<CanvasRenderingContext2D | null>(null);
  const previewContextRef = useRef<CanvasRenderingContext2D | null>(null);
  const brushCursor = useSettingsStore((state) => state.brushCursor);

  useEffect(() => {
    const canvas = canvasRef.current;
    const previewCanvas = previewCanvasRef.current;
    if (!canvas || !previewCanvas) return;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const previewContext = previewCanvas.getContext("2d");
    if (!context || !previewContext) return;
    context.lineCap = "round";
    context.lineJoin = "round";
    previewContext.lineCap = "round";
    previewContext.lineJoin = "round";
    fillWhite(context, canvas.width, canvas.height);
    contextRef.current = context;
    previewContextRef.current = previewContext;
  }, []);

  const renderer = useMemo(
    () => createProtocolRenderer(canvasRef, contextRef),
    [],
  );
  const protocol = useCanvasProtocol(renderer);
  const pointer = useCanvasPointerInput(
    protocol,
    canvasRef,
    contextRef,
    previewCanvasRef,
    previewContextRef,
    { isDrawer, color, brushWidth, tool, brushCursor },
  );

  useImperativeHandle(ref, () => ({
    saveImage: () => saveCanvasImage(canvasRef.current, downloadPrompt),
  }), [downloadPrompt]);

  return (
    <div className="canvas-wrapper">
      <div className="canvas-stack">
        <canvas
          ref={canvasRef}
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
          className={`drawing-canvas${isDrawer ? " drawable" : ""}${pointer.showCircleCursor ? " eraser-tool" : ""}`}
          role="img"
          aria-label={label}
          onPointerDown={pointer.onPointerDown}
          onPointerMove={pointer.onPointerMove}
          onPointerUp={pointer.onPointerUp}
          onPointerLeave={pointer.onPointerLeave}
          onPointerCancel={pointer.onPointerCancel}
        />
        <canvas
          ref={previewCanvasRef}
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
          className="preview-canvas"
          aria-hidden="true"
        />
        {overlay}
      </div>
    </div>
  );
});

export const Canvas = memo(CanvasComponent);
