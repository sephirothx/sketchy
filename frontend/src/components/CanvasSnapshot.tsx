import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { CanvasRef } from "./Canvas";
import { saveCanvasImage } from "../lib/canvasDownload";
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
} from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { renderCanvasActions } from "../lib/canvasRenderer";

interface CanvasSnapshotProps {
  actions: DecodedCanvasAction[];
  downloadPrompt?: string | null;
  label?: string;
}

export const CanvasSnapshot = forwardRef<CanvasRef, CanvasSnapshotProps>(
  function CanvasSnapshot({ actions, downloadPrompt = null, label }, ref) {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);

    useEffect(() => {
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d", { willReadFrequently: true });
      if (!canvas || !context) return;
      renderCanvasActions(context, actions);
    }, [actions]);

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
            className="drawing-canvas"
            role="img"
            aria-label={label ?? (downloadPrompt ? `Drawing of ${downloadPrompt}` : "Saved drawing")}
          />
        </div>
      </div>
    );
  },
);
