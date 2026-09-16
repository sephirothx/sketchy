import assert from "node:assert/strict";
import test from "node:test";

import {
  registerCanvasCommandHandlers,
  requestCanvasClear,
  requestCanvasUndo,
} from "../src/lib/canvasCommands.ts";

function canvas(name, log) {
  return { clear: () => log.push(`${name}:clear`), undo: () => log.push(`${name}:undo`) };
}

test("a pad mounted over the game's canvas takes the commands, and gives them back when it goes", () => {
  const log = [];
  const releaseGame = registerCanvasCommandHandlers(canvas("game", log));
  const releasePad = registerCanvasCommandHandlers(canvas("pad", log));
  requestCanvasUndo();
  releasePad();
  requestCanvasUndo();
  requestCanvasClear();
  releaseGame();
  requestCanvasClear();
  assert.deepEqual(log, ["pad:undo", "game:undo", "game:clear"]);
});

test("the canvas under the pad unmounting first leaves the pad its commands", () => {
  const log = [];
  const releaseGame = registerCanvasCommandHandlers(canvas("game", log));
  const releasePad = registerCanvasCommandHandlers(canvas("pad", log));
  releaseGame();
  requestCanvasClear();
  releasePad();
  assert.deepEqual(log, ["pad:clear"]);
});
