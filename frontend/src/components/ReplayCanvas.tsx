import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { CanvasRef } from "./Canvas";
import { saveCanvasImage } from "../lib/canvasDownload";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "../lib/canvasHistory";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import {
  applyCanvasAction,
  applyCanvasStrokeSpan,
  renderCanvasActions,
  renderCanvasActionsUpTo,
} from "../lib/canvasRenderer";
import { replayPlan, stepReplay, type ReplayPlan } from "../lib/replay";
import { ui } from "../content/ui/index.ts";

interface ReplayCanvasProps {
  actions: DecodedCanvasAction[];
  /** How far through the replay the picture is, 0..1. The page owns it. */
  fraction: number;
  playing: boolean;
  /** Called as playing moves the picture on; the page keeps `fraction` in step. */
  onFraction: (fraction: number) => void;
  onDone?: () => void;
  downloadPrompt?: string | null;
  label?: string;
}

/**
 * The stored frame drawn the way the room saw it happen: strokes grow part
 * of a segment per frame, shapes and fills land in one go, over a few
 * seconds whatever the drawing's size (`replayPlan`). The stored bytes are
 * actions, not a picture (R-HIST-15), which is what makes this possible.
 *
 * The picture is a function of `fraction`: at 1 it is the finished drawing,
 * at 0 white, anywhere between the drawing as far as it had got. Playing
 * advances a cursor frame by frame and reports each fraction back; a
 * fraction set from outside (a scrub) redraws from white up to it.
 */
export const ReplayCanvas = forwardRef<CanvasRef, ReplayCanvasProps>(function ReplayCanvas(
  { actions, fraction, playing, onFraction, onDone, downloadPrompt = null, label },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const bufferRef = useRef<ImageData | null>(null);
  const planRef = useRef<ReplayPlan>(replayPlan(actions));
  const cursor = useRef({ action: actions.length, point: 0 });
  // The last fraction this canvas reported. A prop that differs from it was
  // set by somebody else, and the picture has to be redrawn to match.
  const reported = useRef(fraction);
  const frame = useRef<number | null>(null);
  const callbacks = useRef({ onFraction, onDone });
  callbacks.current = { onFraction, onDone };

  const context = () => canvasRef.current?.getContext("2d", { willReadFrequently: true }) ?? null;

  // First paint, and a new drawing: the picture at the fraction given.
  useEffect(() => {
    const ctx = context();
    const buffer = (bufferRef.current = ctx?.createImageData(CANVAS_WIDTH, CANVAS_HEIGHT) ?? null);
    if (!ctx || !buffer) return;
    const plan = (planRef.current = replayPlan(actions));
    cursor.current = plan.positionAt(fraction);
    renderCanvasActionsUpTo(buffer.data, actions, cursor.current);
    ctx.putImageData(buffer, 0, 0);
    reported.current = fraction;
    // The fraction at mount is the starting point, deliberately not a dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actions]);

  // A fraction set from outside - a scrub, or play pressed at the end -
  // redraws the picture from white up to it. Our own reports come back as
  // the same number and change nothing.
  useEffect(() => {
    const ctx = context();
    const buffer = bufferRef.current;
    if (!ctx || !buffer || fraction === reported.current) return;
    cursor.current = planRef.current.positionAt(fraction);
    renderCanvasActionsUpTo(buffer.data, actions, cursor.current);
    ctx.putImageData(buffer, 0, 0);
    reported.current = fraction;
  }, [actions, fraction]);

  useEffect(() => {
    if (!playing) return;
    const ctx = context();
    const buffer = bufferRef.current;
    if (!ctx || !buffer) return;
    const plan = planRef.current;
    // Playing from the end starts over: nobody presses play to watch nothing.
    if (cursor.current.action >= actions.length) {
      cursor.current = { action: 0, point: 0 };
      renderCanvasActionsUpTo(buffer.data, actions, cursor.current);
      ctx.putImageData(buffer, 0, 0);
    }
    let last = performance.now();
    // What the last frame left of its budget: a whole action costs more than
    // one frame holds, so the debt carries until the pace has paid for it.
    let carry = 0;
    const tick = (now: number) => {
      const elapsed = now - last;
      last = now;
      const budget = carry + (elapsed / 1000) * plan.pointsPerSecond;
      const stepped = stepReplay(actions, plan, cursor.current, budget, {
        span: (stroke, from, to) => applyCanvasStrokeSpan(buffer.data, stroke, from, to),
        whole: (action) => applyCanvasAction(buffer.data, action),
      });
      cursor.current = stepped.position;
      carry = stepped.left;
      ctx.putImageData(buffer, 0, 0);
      const at = plan.fractionAt(stepped.position.action, stepped.position.point);
      reported.current = at;
      callbacks.current.onFraction(at);
      if (stepped.position.action >= actions.length) {
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
  }, [playing, actions]);

  useImperativeHandle(ref, () => ({
    saveImage: () => {
      // Whatever is on screen mid-replay is not the drawing; the file is.
      const canvas = canvasRef.current;
      const ctx = context();
      if (!canvas || !ctx) return;
      const shown = ctx.getImageData(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      renderCanvasActions(ctx, actions);
      saveCanvasImage(canvas, downloadPrompt);
      ctx.putImageData(shown, 0, 0);
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
