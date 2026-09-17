interface CanvasCommandHandlers {
  clear: () => void;
  undo: () => void;
}

/**
 * The canvases that can take Undo and Clear, newest last.
 *
 * A stack rather than one slot because two can be mounted at once: the scratch
 * pad on the card over a paused game (#829) sits on top of the drawer's canvas.
 * The toolbar that is usable is the one on top, so the command goes there; and
 * when that pad goes, the canvas under it gets its commands back rather than
 * being left with none, which is what a single slot cleared on unmount did.
 */
const stack: CanvasCommandHandlers[] = [];

/** Returns the way to take these handlers off again. */
export function registerCanvasCommandHandlers(handlers: CanvasCommandHandlers): () => void {
  stack.push(handlers);
  return () => {
    const index = stack.lastIndexOf(handlers);
    if (index !== -1) stack.splice(index, 1);
  };
}

export function requestCanvasClear(): void {
  stack.at(-1)?.clear();
}

export function requestCanvasUndo(): void {
  stack.at(-1)?.undo();
}
