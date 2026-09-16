import { useEffect, useMemo } from "react";

import type { CanvasProtocol, CanvasProtocolRenderer } from "./useCanvasProtocol";
import type { DecodedCanvasAction } from "../lib/canvasHistory";
import { scratchSheet } from "../lib/scratchPad";

/**
 * The canvas protocol with no server behind it (#829): the scratch pad's.
 *
 * The pointer paints each stroke as it is drawn, exactly as it does for a
 * drawer, and hands the frames here instead of to the room. Here they go into
 * the tab's sheet, and the other pads on screen are told once an action is
 * finished. Undo and clear repaint from the sheet, which is the only truth
 * there is - so an "authoritative sync" is that repaint too.
 */
export function useScratchPadProtocol(renderer: CanvasProtocolRenderer): CanvasProtocol {
  const redraw = useMemo(
    () => (actions: DecodedCanvasAction[]) => renderer.replay(actions),
    [renderer],
  );

  useEffect(() => {
    // Whatever the tab already drew, from an earlier outage or the other pad.
    renderer.replay(scratchSheet.actions);
    return scratchSheet.subscribe(redraw);
  }, [renderer, redraw]);

  return useMemo<CanvasProtocol>(() => ({
    beginDrawAction(frame, isPath = false) {
      if (!scratchSheet.apply(frame)) return null;
      // A path is announced when it ends; a shape or fill is whole already.
      if (!isPath) scratchSheet.changed(redraw);
      return scratchSheet.actions.length;
    },
    sendPathFrame(frame) {
      return scratchSheet.apply(frame);
    },
    finishPathAction() {
      scratchSheet.changed(redraw);
    },
    requestUndo() {
      if (!scratchSheet.undo()) return;
      renderer.replay(scratchSheet.actions);
      scratchSheet.changed(redraw);
    },
    requestClear() {
      if (!scratchSheet.clear()) return;
      renderer.clear();
      scratchSheet.changed(redraw);
    },
    requestAuthoritativeSync() {
      renderer.replay(scratchSheet.actions);
    },
  }), [renderer, redraw]);
}
