import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { PointerEvent as ReactPointerEvent } from "react";

import { DownloadIcon, TrashIcon } from "./icons";
import { ModalShell } from "./ui/ModalShell";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "../lib/canvasHistory";
import type { Point } from "../lib/canvasGeometry";
import { saveCanvasImage } from "../lib/canvasDownload";
import { hexToRgba } from "../lib/canvasPixels";
import { fillWhite, rasterizePolyline } from "../lib/canvasRenderer";
import { SCRATCH_PAD_BRUSH_WIDTH, SCRATCH_PAD_COLORS, padPoint } from "../lib/scratchPad";
import { ui } from "../content/ui/index.ts";

/**
 * What this tab has drawn on the pad so far. One sheet per tab, whichever card
 * the pad is shown on: a connection that drops twice finds the first drawing
 * still there, and a reload - which is the tab starting over - does not.
 */
let sheet: HTMLCanvasElement | null = null;

/**
 * Every pad on screen, redrawn from the sheet when another one changes it.
 * Two can be mounted at once - the waiting room's, and the paused card's over
 * it (#591) - and a pad left showing an older sheet would put that back the
 * next time it was drawn on.
 */
const pads = new Map<HTMLCanvasElement, CanvasRenderingContext2D>();

function keepSheet(canvas: HTMLCanvasElement): void {
  if (!sheet) {
    sheet = document.createElement("canvas");
    sheet.width = CANVAS_WIDTH;
    sheet.height = CANVAS_HEIGHT;
  }
  sheet.getContext("2d")?.drawImage(canvas, 0, 0);
  for (const [other, context] of pads) {
    if (other !== canvas) context.drawImage(sheet, 0, 0);
  }
}

/** The scratch pad (#829, #591): a brush, four colors, Clear and Save, and nothing sent. */
export function ScratchPad() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const contextRef = useRef<CanvasRenderingContext2D | null>(null);
  const strokeRef = useRef<{ pointerId: number; last: Point } | null>(null);
  const [color, setColor] = useState(SCRATCH_PAD_COLORS[0]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d", { willReadFrequently: true });
    if (!canvas || !context) return;
    fillWhite(context, CANVAS_WIDTH, CANVAS_HEIGHT);
    if (sheet) context.drawImage(sheet, 0, 0);
    contextRef.current = context;
    pads.set(canvas, context);
    // The card the pad sits on can go at any moment - the connection is back -
    // and a stroke in progress then never sees its pointerup.
    return () => {
      pads.delete(canvas);
      keepSheet(canvas);
    };
  }, []);

  function paint(points: Point[]): void {
    const context = contextRef.current;
    if (context) rasterizePolyline(context, points, SCRATCH_PAD_BRUSH_WIDTH / 2, hexToRgba(color));
  }

  function onPointerDown(event: ReactPointerEvent<HTMLCanvasElement>): void {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (strokeRef.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const point = padPoint(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect());
    strokeRef.current = { pointerId: event.pointerId, last: point };
    paint([point, point]);
  }

  function onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>): void {
    const stroke = strokeRef.current;
    if (!stroke || stroke.pointerId !== event.pointerId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    // A fast pen reports several samples per frame; drawing only the last one
    // turns a curve into a polygon.
    const samples = event.nativeEvent.getCoalescedEvents?.() ?? [];
    const points = (samples.length ? samples : [event.nativeEvent]).map((sample) =>
      padPoint(sample.clientX, sample.clientY, rect),
    );
    paint([stroke.last, ...points]);
    stroke.last = points[points.length - 1];
  }

  function onPointerEnd(event: ReactPointerEvent<HTMLCanvasElement>): void {
    if (strokeRef.current?.pointerId !== event.pointerId) return;
    strokeRef.current = null;
    keepSheet(event.currentTarget);
  }

  function clear(): void {
    const canvas = canvasRef.current;
    const context = contextRef.current;
    if (!canvas || !context) return;
    fillWhite(context, CANVAS_WIDTH, CANVAS_HEIGHT);
    keepSheet(canvas);
  }

  return (
    <div className="scratch-pad" data-testid="scratch-pad">
      <canvas
        ref={canvasRef}
        className="scratch-pad-canvas"
        width={CANVAS_WIDTH}
        height={CANVAS_HEIGHT}
        role="img"
        aria-label={ui.scratchPad.canvasLabel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
      />
      <div className="scratch-pad-tools">
        <div className="scratch-pad-colors" role="group" aria-label={ui.toolbar.chooseColor}>
          {SCRATCH_PAD_COLORS.map((swatch) => (
            <button
              key={swatch}
              type="button"
              className={`color-swatch${swatch === color ? " selected" : ""}`}
              style={{ backgroundColor: swatch }}
              aria-label={ui.toolbar.colorOption({ color: swatch })}
              aria-pressed={swatch === color}
              onClick={() => setColor(swatch)}
            />
          ))}
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-compact"
          data-testid="scratch-pad-clear"
          onClick={clear}
        >
          <TrashIcon size={15} />
          {ui.scratchPad.clear}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-compact"
          onClick={() => saveCanvasImage(canvasRef.current, "scratch-pad")}
        >
          <DownloadIcon size={15} />
          {ui.scratchPad.save}
        </button>
      </div>
      <p className="scratch-pad-note">{ui.scratchPad.onlyYou}</p>
    </div>
  );
}

/** The pad on its own, for the places that have no card to put it on: outside a room. */
export function ScratchPadDialog({ onClose }: { onClose: () => void }) {
  // Portalled: the banner stack that opens it is sticky, and a fixed layer
  // inside it would be stacked under the page it is meant to cover.
  return createPortal(
    <ModalShell ariaLabel={ui.scratchPad.title} cardClassName="scratch-pad-dialog" onDismiss={onClose}>
      <h3 className="modal-title">{ui.scratchPad.title}</h3>
      <ScratchPad />
      <div className="scratch-pad-dialog-actions">
        <button type="button" className="btn btn-secondary btn-compact" onClick={onClose}>
          {ui.scratchPad.close}
        </button>
      </div>
    </ModalShell>,
    document.body,
  );
}
