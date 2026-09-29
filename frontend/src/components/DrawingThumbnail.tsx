import { useCallback, useEffect, useRef, useState } from "react";

import { CANVAS_WIDTH } from "../lib/canvasHistory";
import { ThumbnailCancelled, ThumbnailDropped, drawThumbnail } from "../lib/thumbnailQueue";

/** A finished drawing at the size it is shown, and nothing kept once it is.

A full `CanvasSnapshot` holds an 800x600 canvas and a second 1.9 MB copy of
its pixels for as long as it is mounted - 3.8 MB a card, whether the card is
a gallery post or a 64 px rail thumbnail, and a gallery scroll never let one
go (#985). A thumbnail needs neither: it is replayed, scaled to the size of
its box and encoded as a small PNG the browser can decode and discard as the
card comes and goes. Nothing on a thumbnail saves an image, which is the one
thing the full-size pixels were kept for; the drawing's own page keeps doing
that.

The replay runs on the thumbnail worker (`lib/thumbnailQueue.ts`, #1282),
never on the page's thread: a history the server accepts can take over a
second to replay. A card that goes, or whose drawing changes, cancels what it
asked for, so no obsolete image is shown and no URL is left behind.

Fetched when it first comes within a screen of the viewport, as the gallery
always did and the pinned shelf now does too. */

/** How long a card with no IntersectionObserver waits to ask again after the
    queue dropped its job. */
const DROPPED_RETRY_MS = 1_000;

/** Draw `bytes` at `cssWidth` CSS pixels as a PNG object URL the caller revokes. */
async function thumbnailUrl(
  bytes: ArrayBuffer,
  cssWidth: number,
  signal: AbortSignal,
): Promise<{ url: string; width: number } | null> {
  const ratio = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
  const image = await drawThumbnail(bytes, (cssWidth || CANVAS_WIDTH / 2) * ratio, signal);
  if (!image) return null;
  return { url: URL.createObjectURL(new Blob([image.png as BlobPart], { type: "image/png" })), width: image.width };
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
  // Bumped to ask again after the queue dropped this card's job.
  const [retry, setRetry] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    loadRef.current = load;
  });

  // Watched both ways until its picture is on screen: a card a scroll takes
  // past before its turn cancels its job and gives its place in the queue to
  // the cards now in view, and asks again if it comes back (#1282 review).
  useEffect(() => {
    if (src !== null || failed || typeof IntersectionObserver === "undefined") return;
    const element = wrapper.current;
    if (!element) return;
    const observer = new IntersectionObserver((records) => {
      const latest = records[records.length - 1];
      if (latest) setVisible(latest.isIntersecting);
    }, { rootMargin: "200px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, [src, failed, retry]);

  // The fetched bytes are kept - a few kilobytes - so the thumbnail can be
  // drawn again at a larger size; the decoded actions and pixels are not.
  const bytesRef = useRef<ArrayBuffer | null>(null);
  const bytesKeyRef = useRef<string | null>(null);
  const encodedWidthRef = useRef(0);

  const encode = useCallback(async (bytes: ArrayBuffer, signal: AbortSignal): Promise<string | null> => {
    const drawn = await thumbnailUrl(bytes, wrapper.current?.clientWidth ?? 0, signal);
    if (!drawn) return null;
    if (signal.aborted) {
      URL.revokeObjectURL(drawn.url);
      throw new ThumbnailCancelled();
    }
    encodedWidthRef.current = drawn.width;
    return drawn.url;
  }, []);

  useEffect(() => {
    if (!visible) return;
    const abort = new AbortController();
    void (async () => {
      try {
        // A card that left and came back asks the worker again, not the server.
        const bytes = bytesKeyRef.current === drawingKey && bytesRef.current
          ? bytesRef.current
          : await loadRef.current();
        if (abort.signal.aborted) return;
        bytesRef.current = bytes;
        bytesKeyRef.current = drawingKey;
        const url = await encode(bytes, abort.signal);
        if (abort.signal.aborted) {
          if (url) URL.revokeObjectURL(url);
          return;
        }
        if (url) setSrc(url);
        else setFailed(true);
      } catch (error) {
        if (abort.signal.aborted || error instanceof ThumbnailCancelled) return;
        // Dropped from a queue a long scroll overfilled: asked for again
        // when the card next comes into view, rather than shown as broken.
        if (!(error instanceof ThumbnailDropped)) {
          setFailed(true);
        } else if (typeof IntersectionObserver === "undefined") {
          // Nothing will say when it is in view again: ask again shortly.
          window.setTimeout(() => setRetry((count) => count + 1), DROPPED_RETRY_MS);
        } else {
          setVisible(false);
          setRetry((count) => count + 1);
        }
      }
    })();
    return () => abort.abort();
  }, [visible, drawingKey, encode, retry]);

  // Each image's URL is let go when it is replaced or the card goes.
  useEffect(() => () => {
    if (src) URL.revokeObjectURL(src);
  }, [src]);

  // Drawn again when the box grows well past the width it was drawn at - a
  // window widened, a phone turned - rather than left upscaled and soft. Not
  // when it shrinks: the browser scales a larger image down cleanly.
  useEffect(() => {
    const element = wrapper.current;
    if (!src || !element || typeof ResizeObserver === "undefined") return;
    let busy = false;
    const abort = new AbortController();
    const observer = new ResizeObserver(() => {
      const ratio = window.devicePixelRatio || 1;
      const wanted = Math.min(CANVAS_WIDTH, Math.round(element.clientWidth * ratio));
      const bytes = bytesRef.current;
      if (busy || !bytes || wanted <= encodedWidthRef.current * 1.25) return;
      busy = true;
      encode(bytes, abort.signal).then(
        (url) => {
          busy = false;
          if (url && abort.signal.aborted) URL.revokeObjectURL(url);
          else if (url) setSrc(url);
        },
        () => {
          // Cancelled, dropped or failed: the image already shown stands.
          busy = false;
        },
      );
    });
    observer.observe(element);
    return () => {
      abort.abort();
      observer.disconnect();
    };
  }, [src, encode]);

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
