/**
 * The scratch pad's drawing (#829, #591): the game's own canvas history, with
 * nobody on the other end of it.
 *
 * The pad draws with the game's canvas and toolbar - every tool, the palette,
 * undo and clear - so it takes the same frames the game sends a server, and
 * keeps them in the same `ClientCanvasHistory` a viewer mirrors. What it never
 * does is send them: there is no socket, no storage and no other player, which
 * is what lets it be offered where the game cannot be played, while the
 * connection is down. Nothing leaves the tab, so there is nothing to moderate.
 *
 * One sheet per tab. A connection that drops twice finds the first drawing
 * still there, and a reload - the tab starting over - does not. Two pads can be
 * on screen at once, the waiting room's under the paused card's, so a change
 * made on one is announced to the others: a pad left showing an older drawing
 * would put it back the next time it was drawn on.
 */

import { ClientCanvasHistory, type DecodedCanvasAction } from "./canvasHistory.ts";
import { decodeLiveDrawing, encodeClear, type DrawingFrame } from "./liveDrawing.ts";

type SheetListener = (actions: DecodedCanvasAction[]) => void;

export class ScratchSheet {
  private readonly history = new ClientCanvasHistory();
  private readonly listeners = new Set<SheetListener>();

  constructor() {
    // A history only takes actions once it has a generation; the pad's is
    // the first and only one, since nothing ever replaces it from outside.
    this.history.reset([0, 1, 0, 0]);
  }

  get actions(): DecodedCanvasAction[] {
    return this.history.actions;
  }

  /** A frame the canvas would have sent. False when it does not apply - no
  path open, undecodable, or a clear of a sheet that is already clear. */
  apply(frame: DrawingFrame): boolean {
    const packet = decodeLiveDrawing(frame, this.history.openPathLastPoint());
    if (!packet || packet.event === "draw_move_relative") return false;
    return this.history.apply(packet);
  }

  clear(): boolean {
    return this.apply(encodeClear());
  }

  /** Takes back the last action, a clear included, as the game's undo does. */
  undo(): boolean {
    // The sequence only has to be newer than the last one confirmed, and on a
    // sheet nobody confirms anything that stays 0.
    return this.history.prepareUndo(1) !== null;
  }

  subscribe(listener: SheetListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Tell every other pad on screen to redraw from the sheet. */
  changed(source: SheetListener): void {
    for (const listener of this.listeners) {
      if (listener !== source) listener(this.history.actions);
    }
  }
}

/** This tab's sheet. */
export const scratchSheet = new ScratchSheet();
