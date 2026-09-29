/** A finished drawing as a small PNG: decoded, replayed, scaled and encoded.

The whole of what a thumbnail costs, in one function that runs the same on a
worker (`workers/thumbnail.worker.ts`, #1282) as on the page when no worker
can be had - so the image is the same bytes either way. No canvas is drawn on
or read (R-DRAW-19): the pixels are replayed, scaled (`canvasThumbnail.ts`)
and encoded (`pngEncode.ts`) in JS.

The replay is the price. It is proportional to what the history makes the
renderer do rather than to its size on the wire: an accepted turn of 100
full-canvas fills is 1.2 KB and repaints 48 million pixels, 1.18 s of
desktop Chromium - on the main thread, a frozen page per such thumbnail. */

import { CANVAS_HEIGHT, CANVAS_WIDTH, decodeCanvasHistory } from "./canvasHistory.ts";
import { renderCanvasActions } from "./canvasRenderer.ts";
import type { CanvasSurface } from "./canvasSurface.ts";
import { downscalePixels } from "./canvasThumbnail.ts";
import { encodePng } from "./pngEncode.ts";

export interface ThumbnailImage {
  png: Uint8Array;
  width: number;
  height: number;
}

/** The size a thumbnail `pixelWidth` device pixels wide is drawn at: never
    wider than the drawing, and never nothing. */
export function thumbnailSize(pixelWidth: number): { width: number; height: number } {
  const width = Math.max(1, Math.min(CANVAS_WIDTH, Math.round(pixelWidth || CANVAS_WIDTH / 2)));
  return { width, height: Math.max(1, Math.round((width * CANVAS_HEIGHT) / CANVAS_WIDTH)) };
}

/** The one full-size buffer this thread's thumbnails are replayed into. The
    replay and the scale are synchronous, so two thumbnails cannot interleave
    on it; the scaled copy is each thumbnail's own. */
let staging: Uint8ClampedArray | null = null;

/** `bytes` drawn `pixelWidth` device pixels wide, or null for a history that
    does not decode. */
export async function renderThumbnail(
  bytes: ArrayBuffer | Uint8Array,
  pixelWidth: number,
): Promise<ThumbnailImage | null> {
  const actions = decodeCanvasHistory(bytes);
  if (!actions) return null;
  staging ??= new Uint8ClampedArray(CANVAS_WIDTH * CANVAS_HEIGHT * 4);
  // The renderer shows its work through `commit`; here the pixels are only
  // read once, at the end, so there is nothing to show along the way.
  const surface: CanvasSurface = { pixels: staging, commit: () => undefined };
  renderCanvasActions(surface, actions);
  const { width, height } = thumbnailSize(pixelWidth);
  const small = width === CANVAS_WIDTH
    ? staging.slice()
    : downscalePixels(staging, CANVAS_WIDTH, CANVAS_HEIGHT, width, height);
  return { png: await encodePng(small, width, height), width, height };
}
