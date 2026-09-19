/** The drawing, held as pixels the game owns; the canvas element only shows them.

Every painter used to read a region of the canvas back, change some pixels and
write it back, and a fill read the whole canvas. A browser is free to answer a
read with other pixels than it painted, and privacy protections do: Firefox's
`privacy.resistFingerprinting` - the default in Tor Browser, Mullvad Browser
and LibreWolf - answers with noise, and the write-back made the noise the
drawing, so every stroke landed in a rectangle of static (measured
2026-09-19). Brave shifts a read by one step, which nobody sees but which is
then written back too.

So the pixels live here, and the canvas is written and never read: a painter
changes `pixels` and calls `commit` with the rectangle it touched, which
copies that rectangle to the screen. No protection alters a write (R-DRAW-19). Reading
the canvas back was also the slow half of painting - a fill fetched the whole
1.9 MB from a canvas that may live on the GPU - and nothing here does it. */

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "./canvasHistory.ts";

export interface CanvasSurface {
  /** CANVAS_WIDTH x CANVAS_HEIGHT RGBA, row by row. The drawing itself. */
  readonly pixels: Uint8ClampedArray;
  /** Show the pixels in this rectangle, clipped to the canvas. */
  commit(x: number, y: number, width: number, height: number): void;
}

/** A layer painted afresh on every move - the stroke preview under the pen -
which is transparent where nothing is painted, and emptied at once. */
export interface LayerSurface extends CanvasSurface {
  /** Everything painted goes: the pixels, and the whole canvas, whatever
  else was drawn on it (the brush cursor is drawn there directly). */
  erase(): void;
}

/** A surface shown on `context`'s canvas, starting white. */
export function createCanvasSurface(context: CanvasRenderingContext2D): CanvasSurface {
  return surfaceOn(context, 255);
}

/** A transparent layer on `context`'s canvas. */
export function createLayerSurface(context: CanvasRenderingContext2D): LayerSurface {
  return surfaceOn(context, 0);
}

function surfaceOn(context: CanvasRenderingContext2D, background: number): LayerSurface {
  const image = context.createImageData(CANVAS_WIDTH, CANVAS_HEIGHT);
  image.data.fill(background);
  context.putImageData(image, 0, 0);
  // What has been painted since the last erase, so an erase clears only that.
  let painted: [number, number, number, number] | null = null;
  return {
    pixels: image.data,
    commit(x, y, width, height) {
      const left = Math.max(0, Math.floor(x));
      const top = Math.max(0, Math.floor(y));
      const right = Math.min(CANVAS_WIDTH, Math.ceil(x + width));
      const bottom = Math.min(CANVAS_HEIGHT, Math.ceil(y + height));
      if (right <= left || bottom <= top) return;
      painted = painted
        ? [Math.min(painted[0], left), Math.min(painted[1], top), Math.max(painted[2], right), Math.max(painted[3], bottom)]
        : [left, top, right, bottom];
      // The dirty-rectangle form: only that rectangle goes to the screen.
      context.putImageData(image, 0, 0, left, top, right - left, bottom - top);
    },
    erase() {
      if (painted) {
        const [left, top, right, bottom] = painted;
        for (let y = top; y < bottom; y++) {
          image.data.fill(background, (y * CANVAS_WIDTH + left) * 4, (y * CANVAS_WIDTH + right) * 4);
        }
        painted = null;
      }
      context.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    },
  };
}

/** Show the whole surface. */
export function commitAll(surface: CanvasSurface): void {
  surface.commit(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
}
