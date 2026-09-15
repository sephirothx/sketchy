import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { CanvasRef } from "./Canvas";
import { saveCanvasImage } from "../lib/canvasDownload";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { applyCanvasAction, applyCanvasPathSpan, renderCanvasActions } from "../lib/canvasRenderer";
import { fillWhitePixels } from "../lib/canvasPixels";
import { replayPlan, stepReplay } from "../lib/replay";
import { ui } from "../content/ui/index.ts";

interface ReplayCanvasProps {
  actions: DecodedCanvasAction[];
  /** Counts up while playing; a new value restarts the drawing from white. */
  run: number;
  playing: boolean;
  onProgress?: (fraction: number) => void;
  onDone?: () => void;
  downloadPrompt?: string | null;
  label?: string;
}

/**
 * The stored frame drawn the way the room saw it happen: strokes grow point
 * by point, shapes and fills land in one go, over a few seconds whatever the
 * drawing's size (`replayPlan`). The stored bytes are actions, not a picture
 * (R-HIST-15), which is what makes this possible at all. Paused, it holds;
 * a finished run shows the finished drawing, the same pixels
 * `renderCanvasActions` would give.
 */
export const ReplayCanvas = forwardRef<CanvasRef, ReplayCanvasProps>(function ReplayCanvas(
  { actions, run, playing, onProgress, onDone, downloadPrompt = null, label },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const bufferRef = useRef<ImageData | null>(null);
  // Where the replay has got to: the next action, and the next point of it.
  const cursor = useRef({ action: 0, point: 0 });
  const frame = useRef<number | null>(null);
  const callbacks = useRef({ onProgress, onDone });
  callbacks.current = { onProgress, onDone };

  // A new run starts from a white canvas.
  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d", { willReadFrequently: true });
    if (!canvas || !context) return;
    const imageData = context.createImageData(CANVAS_WIDTH, CANVAS_HEIGHT);
    fillWhitePixels(imageData.data);
    context.putImageData(imageData, 0, 0);
    bufferRef.current = imageData;
    cursor.current = { action: 0, point: 0 };
    callbacks.current.onProgress?.(0);
  }, [actions, run]);

  useEffect(() => {
    if (!playing) return;
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d", { willReadFrequently: true });
    const buffer = bufferRef.current;
    if (!canvas || !context || !buffer) return;
    const plan = replayPlan(actions);
    let last = performance.now();
    // What the last frame left of its budget: a whole action costs more than
    // one frame holds, so the debt carries until the pace has paid for it.
    let carry = 0;

    const tick = (now: number) => {
      const elapsed = now - last;
      last = now;
      // Segments owed since the last frame, at the plan's pace, fractional:
      // a stroke grows part of a segment per frame rather than a point at a time.
      const budget = carry + (elapsed / 1000) * plan.pointsPerSecond;
      const stepped = stepReplay(actions, plan, cursor.current, budget, {
        span: (action, from, to) => applyCanvasPathSpan(buffer.data, action, from, to),
        whole: (action) => applyCanvasAction(buffer.data, action),
      });
      cursor.current = stepped.position;
      carry = stepped.left;
      const position = stepped.position;
      context.putImageData(buffer, 0, 0);
      callbacks.current.onProgress?.(plan.fractionAt(position.action, position.point));
      if (position.action >= actions.length) {
        frame.current = null;
        callbacks.current.onDone?.();
        return;
      }
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [playing, actions, run]);

  useImperativeHandle(ref, () => ({
    saveImage: () => {
      // Whatever is on screen mid-replay is not the drawing; the file is.
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d", { willReadFrequently: true });
      if (!canvas || !context) return;
      const shown = context.getImageData(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      renderCanvasActions(context, actions);
      saveCanvasImage(canvas, downloadPrompt);
      context.putImageData(shown, 0, 0);
    },
  }), [actions, downloadPrompt]);

  return (
    <div className="canvas-wrapper">
      <div className="canvas-stack">
        <canvas
          ref={canvasRef}
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
          className="drawing-canvas"
          role="img"
          aria-label={label ?? ui.canvasSnapshot.savedDrawing}
        />
      </div>
    </div>
  );
});
