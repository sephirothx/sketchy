import {
  forwardRef,
  memo,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";
import type { ReactNode } from "react";
import { useCanvasPointerInput } from "../hooks/useCanvasPointerInput";
import {
  useCanvasProtocol,
} from "../hooks/useCanvasProtocol";
import { createProtocolRenderer } from "../lib/protocolRenderer";
import type { CanvasProtocol, CanvasProtocolRenderer } from "../hooks/useCanvasProtocol";
import { useScratchPadProtocol } from "../hooks/useScratchPadProtocol";
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "../lib/canvasHistory";
import { useSettingsStore } from "../store/settingsStore";
import { useGameStore } from "../store/gameStore";
import { currentClientConfig } from "../lib/clientConfig";
import type { DrawTool } from "../types";
import { saveCanvasImage } from "../lib/canvasDownload";
import { createCanvasSurface, createLayerSurface, type CanvasSurface, type LayerSurface } from "../lib/canvasSurface";
import { recordRender, type RenderRegion } from "../lib/renderDiagnostics";

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


/**
 * One drawing surface, bound to where its frames go.
 *
 * The game's canvas sends them to the room; the scratch pad's keeps them in the
 * tab (#829). Everything else - the pointer, the preview layer, the brush
 * cursor, undo and clear, the renderer - is the same code, so the pad draws
 * exactly as a turn does. A factory rather than a prop, because which protocol
 * hook runs cannot change over a component's life.
 */
function createCanvas(
  useProtocol: (renderer: CanvasProtocolRenderer) => CanvasProtocol,
  region: RenderRegion,
  unbudgeted: boolean,
  // The cadence whoever produced these frames is flushing at, which is what
  // playback schedules a batch over (R-DRAW-01).
  senderIntervalMs: () => number,
) {
  return forwardRef<CanvasRef, CanvasProps>(function Canvas(
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
    recordRender(region);
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);
    // The drawing's own pixels, and the stroke preview's (`canvasSurface.ts`).
    const surfaceRef = useRef<CanvasSurface | null>(null);
    const previewSurfaceRef = useRef<LayerSurface | null>(null);
    const previewContextRef = useRef<CanvasRenderingContext2D | null>(null);
    const brushCursor = useSettingsStore((state) => state.brushCursor);
    const penPressure = useSettingsStore((state) => state.penPressure);

    useEffect(() => {
      const canvas = canvasRef.current;
      const previewCanvas = previewCanvasRef.current;
      if (!canvas || !previewCanvas) return;
      // Never read (`canvasSurface.ts`), so no `willReadFrequently`: the
      // browser may keep the canvas on the GPU, and only writes reach it.
      const context = canvas.getContext("2d");
      const previewContext = previewCanvas.getContext("2d");
      if (!context || !previewContext) return;
      previewContext.lineCap = "round";
      previewContext.lineJoin = "round";
      surfaceRef.current = createCanvasSurface(context);
      previewSurfaceRef.current = createLayerSurface(previewContext);
      previewContextRef.current = previewContext;
    }, []);

    const renderer = useMemo(
      () => createProtocolRenderer(surfaceRef, senderIntervalMs),
      [],
    );
    // What the renderer holds lives outside React, so React has to let it go
    // (#886): every entry into a room, every scratch pad and every StrictMode
    // double mount used to leave a listener and a playback queue behind. The
    // listener is taken per mount, so a StrictMode remount - which keeps the
    // memoised renderer - watches again rather than going deaf.
    useEffect(() => {
      const stopWatching = renderer.watchHidden();
      return () => {
        stopWatching();
        renderer.dispose();
      };
    }, [renderer]);
    const protocol = useProtocol(renderer);
    const pointer = useCanvasPointerInput(
      protocol,
      canvasRef,
      surfaceRef,
      previewSurfaceRef,
      previewContextRef,
      { isDrawer, color, brushWidth, tool, brushCursor, penPressure, unbudgeted },
    );

    useImperativeHandle(ref, () => ({
      saveImage: () => void saveCanvasImage(surfaceRef.current?.pixels ?? null, downloadPrompt),
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
}

/** The drawing seat's cadence, as the server most recently stated it, or the
baseline until a turn does. A getter rather than a subscription: playback reads
it when it schedules a batch, and a turn that changes it has already re-sent
`turn_started` by then. */
const drawerInterval = () =>
  useGameStore.getState().drawerFlushIntervalMs ?? currentClientConfig().flushIntervalMs;

export const Canvas = memo(createCanvas(useCanvasProtocol, "canvas", false, drawerInterval));

/** The scratch pad's canvas: nothing it draws leaves the tab, so its sender is
this client and the baseline is what `useCanvasPointerInput` flushes it at. It
never pays the polling cadence: that cadence buys bytes on a transport the pad
does not use (#829). */
const padInterval = () => currentClientConfig().flushIntervalMs;

export const ScratchPadCanvas = memo(
  createCanvas(useScratchPadProtocol, "scratchPad", true, padInterval),
);
