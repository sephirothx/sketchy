interface CanvasCommandHandlers {
  clear: () => void;
  undo: () => void;
}

let handlers: CanvasCommandHandlers | null = null;

export function registerCanvasCommandHandlers(
  nextHandlers: CanvasCommandHandlers | null,
): void {
  handlers = nextHandlers;
}

export function requestCanvasClear(): void {
  handlers?.clear();
}

export function requestCanvasUndo(): void {
  handlers?.undo();
}
