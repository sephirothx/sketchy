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
import type { Point } from "../lib/canvasGeometry";
import type { LiveDrawingPacket } from "../lib/liveDrawing";
import { useSettingsStore } from "../store/settingsStore";
import type { DrawTool, StrokePoint } from "../types";
import { saveCanvasImage } from "../lib/canvasDownload";
import { recordRender } from "../lib/renderDiagnostics";

interface CanvasProps {
  isDrawer: boolean;
  color: string;
  brushWidth: number;
  tool: DrawTool;
  solutionPrompt?: string | null;
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

  const clear = () => {
    replayGeneration += 1;
    const canvas = canvasRef.current;
    const context = contextRef.current;
    if (canvas && context) fillWhite(context, canvas.width, canvas.height);
    remoteState.last = null;
  };

  const apply = (packet: LiveDrawingPacket) => {
    const context = contextRef.current;
    if (!context) return;
    if (packet.event === "draw_start") {
      remoteState.last = { x: packet.payload.x, y: packet.payload.y };
      remoteState.color = packet.payload.color;
      remoteState.width = packet.payload.width;
      const point = toPixels(remoteState.last);
      rasterizePolyline(
        context,
        [point, point],
        remoteState.width / 2,
        hexToRgba(remoteState.color),
      );
    } else if (packet.event === "draw_move") {
      if (!remoteState.last || packet.payload.points.length === 0) return;
      const polyline: Point[] = [toPixels(remoteState.last)];
      packet.payload.points.forEach((point) => polyline.push(toPixels(point)));
      rasterizePolyline(
        context,
        polyline,
        remoteState.width / 2,
        hexToRgba(remoteState.color),
      );
      remoteState.last = packet.payload.points.at(-1)!;
    } else if (packet.event === "draw_end") {
      remoteState.last = null;
    } else if (packet.event === "draw_shape") {
      const payload = packet.payload;
      drawShapeOutlinePixels(
        context,
        payload.from,
        payload.to,
        payload.shape,
        payload.color,
        payload.width,
      );
    } else if (packet.event === "draw_fill") {
      applyFillAction(context, packet.payload);
    } else {
      clear();
    }
  };

  const replay = (actions: DecodedCanvasAction[]) => {
    const currentReplay = ++replayGeneration;
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
    solutionPrompt = null,
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
    saveImage: () => saveCanvasImage(canvasRef.current, solutionPrompt),
  }), [solutionPrompt]);

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
