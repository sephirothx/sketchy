import { useEffect, useRef, useState } from "react";

import { CANVAS_HEIGHT, CANVAS_WIDTH, decodeCanvasHistory, type DecodedCanvasAction } from "../lib/canvasHistory";
import { renderCanvasActions } from "../lib/canvasRenderer";
import type { CanvasSurface } from "../lib/canvasSurface";

/** A finished drawing at the size it is shown, and nothing kept once it is.

A full `CanvasSnapshot` holds an 800x600 canvas and a second 1.9 MB copy of
its pixels for as long as it is mounted - 3.8 MB a card, whether the card is
a gallery post or a 64 px rail thumbnail, and a gallery scroll never let one
go (#985). A thumbnail needs neither: it is replayed into one buffer every
thumbnail shares, scaled once into a canvas the size of its box, and the
buffer, the decoded actions and the bytes are all free the moment it is on
screen, as a small PNG the browser can decode and discard as the card comes
and goes. Nothing on a thumbnail saves an image, which is the one thing the
full-size pixels were kept for; the drawing's own page keeps doing that.

Fetched when it first comes within a screen of the viewport, as the gallery
always did and the pinned shelf now does too. */

let staging: { pixels: Uint8ClampedArray; image: ImageData; context: CanvasRenderingContext2D } | null = null;
let scaled: CanvasRenderingContext2D | null = null;

/** The one full-size buffer and canvas every thumbnail is replayed through,
    and the one canvas it is scaled into. */
function stagingSurfaces() {
  if (!staging) {
    const canvas = document.createElement("canvas");
    canvas.width = CANVAS_WIDTH;
    canvas.height = CANVAS_HEIGHT;
    const context = canvas.getContext("2d");
    if (!context) return null;
    const image = context.createImageData(CANVAS_WIDTH, CANVAS_HEIGHT);
    staging = { pixels: image.data, image, context };
  }
  scaled ??= document.createElement("canvas").getContext("2d");
  return scaled ? { ...staging, scaled } : null;
}

/** Replay `actions` and encode them at `cssWidth` CSS pixels, as an object
    URL the caller revokes. Everything up to `toBlob` is synchronous, so two
    thumbnails cannot interleave on the shared canvases, and `toBlob` copies
    the pixels before it returns. */
function thumbnailUrl(actions: DecodedCanvasAction[], cssWidth: number): Promise<string | null> {
  const shared = stagingSurfaces();
  if (!shared) return Promise.resolve(null);
  // The renderer shows its work through `commit`; here the pixels are only
  // read once, at the end, so there is nothing to show along the way.
  const surface: CanvasSurface = { pixels: shared.pixels, commit: () => undefined };
  renderCanvasActions(surface, actions);
  shared.context.putImageData(shared.image, 0, 0);
  const ratio = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
  const width = Math.max(1, Math.min(CANVAS_WIDTH, Math.round((cssWidth || CANVAS_WIDTH / 2) * ratio)));
  const target = shared.scaled;
  target.canvas.width = width;
  target.canvas.height = Math.max(1, Math.round((width * CANVAS_HEIGHT) / CANVAS_WIDTH));
  target.imageSmoothingEnabled = true;
  target.imageSmoothingQuality = "high";
  target.drawImage(shared.context.canvas, 0, 0, target.canvas.width, target.canvas.height);
  return new Promise((resolve) => {
    target.canvas.toBlob((blob) => resolve(blob ? URL.createObjectURL(blob) : null), "image/png");
  });
}

export function DrawingThumbnail({
  drawingKey,
  load,
  label,
  className,
  noteClassName,
  failedText,
}: {
  /** Changes when the drawing does; the fetch runs again only then. */
  drawingKey: string;
  load: () => Promise<ArrayBuffer>;
  label: string;
  className: string;
  noteClassName: string;
  failedText: string;
}) {
  const wrapper = useRef<HTMLDivElement | null>(null);
  const loadRef = useRef(load);
  const [visible, setVisible] = useState(typeof IntersectionObserver === "undefined");
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    if (visible || typeof IntersectionObserver === "undefined") return;
    const element = wrapper.current;
    if (!element) return;
    const observer = new IntersectionObserver((records) => {
      if (records.some((record) => record.isIntersecting)) setVisible(true);
    }, { rootMargin: "200px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    let current = true;
    let url: string | null = null;
    void (async () => {
      try {
        const bytes = await loadRef.current();
        if (!current) return;
        const actions = decodeCanvasHistory(bytes);
        url = actions ? await thumbnailUrl(actions, wrapper.current?.clientWidth ?? 0) : null;
        if (!current) {
          if (url) URL.revokeObjectURL(url);
          return;
        }
        if (url) setSrc(url);
        else setFailed(true);
      } catch {
        if (current) setFailed(true);
      }
    })();
    return () => {
      current = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [visible, drawingKey]);

  // An image rather than a canvas: the browser may drop an off-screen
  // image's decoded pixels and decode them again when it scrolls back, which
  // it never does for a canvas - so a long gallery scroll holds a few dozen
  // kilobytes of PNG per card, not a bitmap.
  return (
    <div ref={wrapper} className={className} aria-busy={!src && !failed}>
      {failed ? (
        <span className={noteClassName}>{failedText}</span>
      ) : src === null ? null : (
        <div className="canvas-wrapper">
          <div className="canvas-stack">
            <img src={src} className="drawing-canvas" alt={label} decoding="async" draggable={false} />
          </div>
        </div>
      )}
    </div>
  );
}
