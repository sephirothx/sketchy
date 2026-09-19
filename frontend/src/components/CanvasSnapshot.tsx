import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { CanvasRef } from "./Canvas";
import { saveCanvasImage } from "../lib/canvasDownload";
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { renderCanvasActions } from "../lib/canvasRenderer";
import { createCanvasSurface, type CanvasSurface } from "../lib/canvasSurface";
import { ui } from "../content/ui/index.ts";

interface CanvasSnapshotProps {
  actions: DecodedCanvasAction[];
  downloadPrompt?: string | null;
  label?: string;
}

export const CanvasSnapshot = forwardRef<CanvasRef, CanvasSnapshotProps>(
  function CanvasSnapshot({ actions, downloadPrompt = null, label }, ref) {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const surfaceRef = useRef<CanvasSurface | null>(null);

    useEffect(() => {
      const context = canvasRef.current?.getContext("2d");
      if (!context) return;
      surfaceRef.current ??= createCanvasSurface(context);
      renderCanvasActions(surfaceRef.current, actions);
    }, [actions]);

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
            className="drawing-canvas"
            role="img"
            aria-label={label ?? (downloadPrompt ? ui.canvasSnapshot.drawingOfDownloadPrompt({ downloadPrompt }) : ui.canvasSnapshot.savedDrawing)}
          />
        </div>
      </div>
    );
  },
);
