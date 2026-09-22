import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

/* The drawing canvas is written and never read (`canvasSurface.ts`): a
browser may answer a read with other pixels than it painted, and a painter
that wrote them back made the noise the drawing. A read that creeps back into
the code that paints or saves the drawing fails here. */

const DRAWING_CODE = [
  "src/components/Canvas.tsx",
  "src/components/CanvasSnapshot.tsx",
  "src/components/DrawingThumbnail.tsx",
  "src/components/ReplayCanvas.tsx",
  "src/components/ScratchPad.tsx",
  "src/hooks/useCanvasPointerInput.ts",
  "src/hooks/useCanvasProtocol.ts",
  "src/hooks/useScratchPadProtocol.ts",
  // The replay benchmark paints with the real renderer, so it holds the drawing the same way.
  "benchmarks/canvas-history.html",
  ...readdirSync("src/lib").filter((file) => /^(canvas(?!Readback)|strokePlayback|replay|pngEncode|pathWidths|penStroke)/.test(file)).map((file) => `src/lib/${file}`),
];

test("nothing that paints or saves the drawing reads a canvas", () => {
  assert.ok(DRAWING_CODE.includes("src/lib/canvasRenderer.ts"));
  for (const file of DRAWING_CODE) {
    // Comments may name the calls; code may not make them.
    const code = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    for (const read of ["getImageData", "toDataURL", "toBlob", "willReadFrequently"]) {
      assert.ok(!code.includes(read), `${file} calls ${read}`);
    }
  }
});
