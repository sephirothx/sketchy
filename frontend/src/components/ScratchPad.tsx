import { useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ScratchPadCanvas, type CanvasRef } from "./Canvas";
import { Toolbar } from "./Toolbar";
import { ModalShell } from "./ui/ModalShell";
import type { DrawTool } from "../types";
import { DEFAULT_ERASER_SIZE } from "../lib/brushSizes";
import { useSettingsStore } from "../store/settingsStore";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/toolbar.css";

/**
 * The scratch pad (#829, #591): the game's canvas and toolbar, with nothing
 * sent. Game-sized wherever it is shown, because it is for drawing on.
 *
 * The tools start where a turn starts them - black brush, 6px, a 24px eraser -
 * and are this pad's own, so what somebody picks up here is not what they hold
 * when their turn comes.
 */
export function ScratchPad() {
  const canvasRef = useRef<CanvasRef | null>(null);
  const [color, setColor] = useState("#000000");
  const [tool, setTool] = useState<DrawTool>("brush");
  const defaultBrushSize = useSettingsStore((state) => state.defaultBrushSize);
  const [brushWidth, setBrushWidth] = useState<number>(defaultBrushSize);
  const [eraserWidth, setEraserWidth] = useState<number>(DEFAULT_ERASER_SIZE);
  const width = tool === "eraser" ? eraserWidth : brushWidth;

  return (
    <div className="scratch-pad" data-testid="scratch-pad">
      <ScratchPadCanvas
        ref={canvasRef}
        isDrawer
        color={color}
        brushWidth={width}
        tool={tool}
        downloadPrompt="scratch-pad"
        label={ui.scratchPad.canvasLabel}
      />
      {/* Its own column: the toolbar picks its arrangement from the width of
          the element it sits in. */}
      <div className="scratch-pad-toolbar">
        <Toolbar
          scratchPad
          color={color}
          onColorChange={setColor}
          brushWidth={width}
          onBrushWidthChange={(next) => (tool === "eraser" ? setEraserWidth(next) : setBrushWidth(next))}
          tool={tool}
          onToolChange={setTool}
          onSave={() => canvasRef.current?.saveImage()}
        />
      </div>
    </div>
  );
}

/** The pad on its own, for the places that have no card to put it on: outside a room. */
export function ScratchPadDialog({ onClose }: { onClose: () => void }) {
  // Portalled: the banner stack that opens it is sticky, and a fixed layer
  // inside it would be stacked under the page it is meant to cover.
  return createPortal(
    <ModalShell ariaLabel={ui.scratchPad.title} cardClassName="scratch-pad-dialog" onDismiss={onClose}>
      <div className="scratch-pad-dialog-head">
        <h3 className="modal-title">{ui.scratchPad.title}</h3>
        <button type="button" className="btn btn-secondary btn-compact" onClick={onClose}>
          {ui.scratchPad.close}
        </button>
      </div>
      <ScratchPad />
    </ModalShell>,
    document.body,
  );
}
