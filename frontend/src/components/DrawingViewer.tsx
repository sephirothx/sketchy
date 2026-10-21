import { Fragment, memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { PointerEvent as ReactPointerEvent, ReactNode, RefObject } from "react";
import { DrawingThumbnail } from "./DrawingThumbnail";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronsLeftIcon,
  ChevronsRightIcon,
  DownloadIcon,
  GridIcon,
  XIcon,
} from "./icons";
import { CANVAS_HEIGHT, CANVAS_WIDTH, decodeCanvasHistory } from "../lib/canvasHistory";
import { renderCanvasActionsUpTo } from "../lib/canvasRenderer";
import { saveCanvasImage } from "../lib/canvasDownload";
import { drawThumbnail } from "../lib/thumbnailQueue";
import { socketRequestErrorMessage } from "../lib/socket";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { PHONE_ROOM_QUERY } from "../lib/roomLayout";
import {
  ARROWS_SHOWN_MS,
  DESKTOP_STRIP_SIZE,
  DOUBLE_TAP_MS,
  ZOOM_SCALE,
  arrowKeyMoves,
  clampPan,
  closesOnRelease,
  dragAxis,
  dragOffset,
  lastStripStart,
  offersOverview,
  slideDurationMs,
  stripStartAfterMove,
  stripStartFor,
  swipeOutcome,
  zoomOriginOffset,
  type DragAxis,
} from "../lib/drawingViewer";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useBackCloses } from "../hooks/useRoomHistory";
import type { DrawingRecapMetadata } from "../types";
import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";
import "../styles/lazy/drawing-viewer.css";
import "../styles/lazy/reactions.css";

/** The one viewer for a finished game's drawings (#1497): the Recap at game
over, game history on the profile, and the pinned shelf all open it.

It opens over the page as a dialog. The drawing sits in a card under its prompt
and drawer; Pin, Share, Save image and the reaction ride on the drawing's lower
corners on a desktop, and sit in a row under it on a phone. A strip of
thumbnails below is the way to any drawing in one tap, which is also what keeps
swiping optional (WCAG 2.5.1): eight at a time with buttons for the next eight
on a desktop, all of them in a row that scrolls on a phone. Above
`OVERVIEW_THRESHOLD` drawings an overview of the whole game is offered too.

Moving between drawings slides: a swipe carries on from where the finger let
go, and the arrows, a thumbnail or the overview slide the drawing in from the
side it lies on. The track holds three slots - previous, current, next - and a
slide ends by swapping the middle one with transitions off, so the jump back
to the centre is never seen. A move asked for while a slide runs finishes that
one at once and slides again from there, so held keys and quick taps never
play a slide backwards. Under reduced motion the drawing simply changes.

Drawings are drawn on the thumbnail worker at their full 800 px, never on the
page's thread (#1282), so a fill-heavy neighbour being prepared cannot stall a
swipe. Save image replays the strokes to pixels of its own (R-DRAW-19). */

interface DrawingViewerProps {
  entries: DrawingRecapMetadata[];
  onClose: () => void;
  /**
   * Fetches one drawing's canvas bytes. A live room asks its socket for a
   * recap it still holds; a finished game asks the API for a stored one. The
   * viewer does not care which, because both answer in the wire format.
   */
  loadEntry: (entry: DrawingRecapMetadata) => Promise<ArrayBuffer | unknown>;
  /** Which drawing to open on. The rest stay reachable from the controls. */
  initialIndex?: number;
  /**
   * The reaction control for one entry. A prop for the same reason `loadEntry`
   * is: the live room reacts over its socket and history over HTTP, and the
   * viewer does not care which.
   */
  renderReactions?: (entry: DrawingRecapMetadata) => ReactNode;
  /** The controls beside Save image - Share and Pin (#440, #1430). A prop for
      the same reason `renderReactions` is. */
  renderActions?: (entry: DrawingRecapMetadata) => ReactNode;
  /** Told the drawing on screen as it changes, so a viewer opened again -
      after the room's connection came back, say - opens where it was left. */
  onIndexChange?: (index: number) => void;
}

interface Slide {
  to: number;
  direction: 1 | -1;
  ms: number;
}

interface PointerTrack {
  id: number;
  x: number;
  y: number;
  at: number;
  axis: DragAxis | null;
  width: number;
  height: number;
  left: number;
  top: number;
  panX: number;
  panY: number;
}

/** Drawn pictures kept for a quick way back; each is a PNG of a few dozen
    kilobytes until the browser decodes it. The ones about to be shown are
    never the ones let go. */
const KEPT_IMAGES = 12;

/** How many drawings either side are drawn before they are reached. */
const PREPARED_EITHER_SIDE = 2;

function entryKey(entry: DrawingRecapMetadata): string {
  return `${entry.index}:${entry.turnId}`;
}

/** The bytes a loader answered with, as the worker needs them. */
function asArrayBuffer(payload: unknown): ArrayBuffer {
  if (payload instanceof ArrayBuffer) return payload;
  if (ArrayBuffer.isView(payload)) {
    return payload.buffer.slice(payload.byteOffset, payload.byteOffset + payload.byteLength) as ArrayBuffer;
  }
  throw new Error(ui.drawingRecapGallery.thisDrawingCouldNotBeDecoded);
}

function entryLabel(target: DrawingRecapMetadata): string {
  return ui.drawingRecapGallery.drawingLabel({ prompt: target.prompt, drawer: target.drawerNickname });
}

/** Two frames: one to paint what changed with transitions off, one more
    before they may run again. */
function afterTwoFrames(frames: number[], then: () => void) {
  const first = requestAnimationFrame(() => {
    frames.push(requestAnimationFrame(then));
  });
  frames.push(first);
}

export function DrawingViewer({
  entries,
  onClose,
  loadEntry,
  initialIndex = 0,
  renderReactions,
  renderActions,
  onIndexChange,
}: DrawingViewerProps) {
  const total = entries.length;
  const phone = useMediaQuery(PHONE_ROOM_QUERY);
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const [index, setIndex] = useState(() => Math.max(0, Math.min(total - 1, initialIndex)));
  const [slide, setSlide] = useState<Slide | null>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  // On for the one render that swaps the middle slot, so the track's jump
  // back to the centre is not animated.
  const [instant, setInstant] = useState(false);
  const [zoom, setZoom] = useState<{ x: number; y: number } | null>(null);
  const [arrowsShown, setArrowsShown] = useState(false);
  const [overviewOpen, setOverviewOpen] = useState(false);
  const [stripStart, setStripStart] = useState(() => stripStartFor(initialIndex, DESKTOP_STRIP_SIZE));
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const stripRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const backRef = useRef<HTMLButtonElement | null>(null);
  const initialFocusRef = useRef<HTMLElement | null>(null);
  const pointerRef = useRef<PointerTrack | null>(null);
  const slideTimer = useRef<number | null>(null);
  const tapTimer = useRef<number | null>(null);
  const arrowsTimer = useRef<number | null>(null);
  const frames = useRef<number[]>([]);
  // A move asked for while a slide runs: made once that slide has settled.
  const queued = useRef<number | null>(null);

  // Settled drawing and the one a slide is heading for: the header, the
  // controls and the strip already show where it is going.
  const current = Math.min(index, Math.max(0, total - 1));
  const shown = slide ? Math.min(slide.to, total - 1) : current;
  const entry = entries[shown] as DrawingRecapMetadata | undefined;

  // A loader is often an inline arrow, a new function every render; the
  // cache must not be thrown away with it.
  const loadEntryRef = useRef(loadEntry);
  useEffect(() => {
    loadEntryRef.current = loadEntry;
  });
  const bytes = useRef(new Map<string, Promise<ArrayBuffer>>());
  const loadBytes = useCallback((target: DrawingRecapMetadata): Promise<ArrayBuffer> => {
    const key = entryKey(target);
    let pending = bytes.current.get(key);
    if (!pending) {
      pending = Promise.resolve(loadEntryRef.current(target)).then(asArrayBuffer);
      bytes.current.set(key, pending);
      const settled = pending;
      // A failure is not kept: Try again asks the server again.
      settled.catch(() => {
        if (bytes.current.get(key) === settled) bytes.current.delete(key);
      });
    }
    return pending;
  }, []);

  // Drawn pictures, by drawing. A slot that becomes the middle one at the end
  // of a slide must show its picture in the same frame, not after another
  // trip to the worker, or the swap would flash; so the pictures outlive the
  // slots, a few at a time, in the order they were last asked for.
  const images = useRef(new Map<string, string>());
  // What render reads: the same pictures, as state.
  const [ready, setReady] = useState<ReadonlyMap<string, string>>(() => new Map());
  const drawing = useRef(new Map<string, Promise<string>>());
  const keep = useRef(new Set<string>());
  // Aborted when the viewer closes. Made by the mount rather than once per
  // instance: StrictMode mounts, unmounts and mounts again, and a controller
  // the first unmount aborted would refuse every drawing after it.
  const closed = useRef<AbortController | null>(null);
  const drawImage = useCallback((target: DrawingRecapMetadata): Promise<string> => {
    const key = entryKey(target);
    const hit = images.current.get(key);
    if (hit) {
      images.current.delete(key);
      images.current.set(key, hit);
      return Promise.resolve(hit);
    }
    let pending = drawing.current.get(key);
    if (!pending) {
      const signal = closed.current?.signal;
      pending = loadBytes(target)
        .then((loaded) => drawThumbnail(loaded, CANVAS_WIDTH, signal))
        .then((image) => {
          if (!image) throw new Error(ui.drawingRecapGallery.thisDrawingCouldNotBeDecoded);
          const url = URL.createObjectURL(new Blob([image.png as BlobPart], { type: "image/png" }));
          if (signal?.aborted) {
            URL.revokeObjectURL(url);
            return url;
          }
          images.current.set(key, url);
          for (const [oldKey, oldUrl] of [...images.current]) {
            if (images.current.size <= KEPT_IMAGES) break;
            if (keep.current.has(oldKey)) continue;
            images.current.delete(oldKey);
            URL.revokeObjectURL(oldUrl);
          }
          setReady(new Map(images.current));
          return url;
        })
        .finally(() => drawing.current.delete(key));
      drawing.current.set(key, pending);
    }
    return pending;
  }, [loadBytes]);

  useEffect(() => {
    const abort = new AbortController();
    closed.current = abort;
    const pictures = images.current;
    const pending = drawing.current;
    const timers = { slide: slideTimer, tap: tapTimer, arrows: arrowsTimer };
    const pendingFrames = frames.current;
    return () => {
      abort.abort();
      // The slides draw before this effect runs on a remount; they must not
      // pick up the controller just aborted.
      if (closed.current === abort) closed.current = null;
      pictures.forEach((url) => URL.revokeObjectURL(url));
      pictures.clear();
      // A draw started under this mount is not one a later mount may reuse.
      pending.clear();
      setReady(new Map());
      Object.values(timers).forEach((timer) => {
        if (timer.current !== null) window.clearTimeout(timer.current);
      });
      pendingFrames.forEach((frame) => cancelAnimationFrame(frame));
    };
  }, []);

  // The page under the viewer does not scroll while it is open.
  useEffect(() => {
    const body = document.body;
    const before = body.style.overflow;
    body.style.overflow = "hidden";
    return () => {
      body.style.overflow = before;
    };
  }, []);

  // The move after the current one, read when a settled slide asks for it.
  const goToRef = useRef<(target: number, dragged?: number) => void>(() => undefined);

  const finishSlide = useCallback((to: number) => {
    if (slideTimer.current !== null) window.clearTimeout(slideTimer.current);
    slideTimer.current = null;
    setInstant(true);
    setIndex(to);
    setSlide(null);
    setOffset({ x: 0, y: 0 });
    afterTwoFrames(frames.current, () => {
      setInstant(false);
      const next = queued.current;
      queued.current = null;
      if (next !== null) goToRef.current(next);
    });
  }, []);

  const goTo = useCallback((target: number, dragged = 0) => {
    const to = Math.max(0, Math.min(total - 1, target));
    setZoom(null);
    setDragging(false);
    setStripStart((start) => stripStartAfterMove(start, to, DESKTOP_STRIP_SIZE));
    // A move is already waiting for a slide to settle: this one replaces it.
    if (queued.current !== null) {
      queued.current = to;
      return;
    }
    if (slide) {
      // Settle the running slide where it was going, then move on from there.
      queued.current = to;
      finishSlide(slide.to);
      return;
    }
    if (to === current) {
      setOffset({ x: 0, y: 0 });
      return;
    }
    if (reducedMotion) {
      setInstant(true);
      setIndex(to);
      setOffset({ x: 0, y: 0 });
      afterTwoFrames(frames.current, () => setInstant(false));
      return;
    }
    const width = frameRef.current?.clientWidth ?? 0;
    const ms = slideDurationMs(dragged, width);
    setSlide({ to, direction: to > current ? 1 : -1, ms });
    setOffset({ x: 0, y: 0 });
    slideTimer.current = window.setTimeout(() => finishSlide(to), ms);
  }, [current, finishSlide, reducedMotion, slide, total]);

  useEffect(() => {
    goToRef.current = goTo;
  });

  const pick = useCallback((target: number) => goToRef.current(target), []);
  // From the overview the stage has to be back on screen before a slide can
  // start, or there would be nothing to slide from.
  const pickFromOverview = useCallback((target: number) => {
    setOverviewOpen(false);
    afterTwoFrames(frames.current, () => goToRef.current(target));
  }, []);

  const closeOverview = useCallback(() => setOverviewOpen(false), []);
  useBackCloses(overviewOpen, closeOverview);
  useLayoutEffect(() => {
    initialFocusRef.current = stripRef.current?.querySelector<HTMLElement>('[aria-current="true"]') ?? null;
  });
  useFocusTrap(dialogRef, {
    onEscape: () => (overviewOpen ? closeOverview() : onClose()),
    initialFocusRef,
  });

  // Focus that would fall to the page - a focused arrow disabled at the end,
  // the phone's arrows hidden again, the overview opening or closing over the
  // control that had it - comes back to the drawing's thumbnail instead.
  useEffect(() => {
    const active = document.activeElement;
    if (active && active !== document.body) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const target = overviewOpen
      ? backRef.current
      : stripRef.current?.querySelector<HTMLElement>('[aria-current="true"]') ?? closeRef.current;
    target?.focus({ preventScroll: true });
  });

  useEffect(() => {
    if (overviewOpen) backRef.current?.focus({ preventScroll: true });
  }, [overviewOpen]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (overviewOpen) return;
      // Not from inside something laid over the viewer: the take-out
      // confirmation, the reaction picker.
      const target = event.target instanceof Element ? event.target : null;
      const layer = target?.closest('[role="dialog"], [role="alertdialog"]');
      if (layer && layer !== dialogRef.current) return;
      const move = arrowKeyMoves({
        key: event.key,
        defaultPrevented: event.defaultPrevented,
        altKey: event.altKey,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        target: target as HTMLElement | null,
      });
      if (move === "previous" && shown > 0) goTo(shown - 1);
      if (move === "next" && shown < total - 1) goTo(shown + 1);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [goTo, overviewOpen, shown, total]);

  // On a phone the strip scrolls; keep the drawing on screen in view, and
  // scroll nothing but the strip to do it.
  useLayoutEffect(() => {
    const strip = stripRef.current;
    if (!phone || !strip || overviewOpen) return;
    const thumb = strip.querySelector<HTMLElement>('[aria-current="true"]');
    if (!thumb) return;
    const left = thumb.offsetLeft - (strip.clientWidth - thumb.offsetWidth) / 2;
    strip.scrollTo({ left: Math.max(0, left), behavior: reducedMotion ? "auto" : "smooth" });
  }, [phone, shown, overviewOpen, reducedMotion]);

  // The drawings a swipe is about to reach are drawn before it gets there,
  // and kept while they are this close - marked as kept in the commit that
  // mounts their slots, before a draw finishing could evict them.
  const near = useMemo(() => {
    const found: DrawingRecapMetadata[] = [];
    for (let step = -PREPARED_EITHER_SIDE; step <= PREPARED_EITHER_SIDE; step += 1) {
      for (const at of [current + step, shown + step]) {
        const target = entries[at];
        if (target && target.available !== false) found.push(target);
      }
    }
    return found;
  }, [current, entries, shown]);
  useLayoutEffect(() => {
    keep.current = new Set(near.map(entryKey));
  }, [near]);
  useEffect(() => {
    near.forEach((target) => drawImage(target).catch(() => undefined));
  }, [drawImage, near]);

  useEffect(() => {
    onIndexChange?.(shown);
  }, [onIndexChange, shown]);

  const showArrowsForAWhile = useCallback(() => {
    if (arrowsTimer.current !== null) window.clearTimeout(arrowsTimer.current);
    setArrowsShown(true);
    arrowsTimer.current = window.setTimeout(() => setArrowsShown(false), ARROWS_SHOWN_MS);
  }, []);

  const currentEntry = entries[current] as DrawingRecapMetadata | undefined;
  const currentPicture = currentEntry ? ready.get(entryKey(currentEntry)) : undefined;

  // One pointer, four gestures on the drawing: a sideways drag changes it, a
  // downward drag closes the viewer, a double tap zooms, and on a phone a
  // single tap shows the arrows for a few seconds. A second pointer - a
  // pinch - calls the whole gesture off rather than being read as the first.
  const cancelGesture = () => {
    pointerRef.current = null;
    setDragging(false);
    setOffset({ x: 0, y: 0 });
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (pointerRef.current) {
      cancelGesture();
      return;
    }
    const target = event.target as HTMLElement;
    if (target.closest("button, a, input, .drawing-viewer-tools, .reaction-picker")) return;
    if (slide) finishSlide(slide.to);
    const rect = event.currentTarget.getBoundingClientRect();
    pointerRef.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      at: performance.now(),
      axis: null,
      width: rect.width,
      height: rect.height,
      left: rect.left,
      top: rect.top,
      panX: zoom?.x ?? 0,
      panY: zoom?.y ?? 0,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const track = pointerRef.current;
    if (!track || event.pointerId !== track.id) return;
    const dx = event.clientX - track.x;
    const dy = event.clientY - track.y;
    if (zoom) {
      if (!track.axis && dragAxis(dx, dy)) track.axis = "x";
      if (track.axis) {
        setDragging(true);
        setZoom(clampPan(track.panX + dx, track.panY + dy, track.width, track.height));
      }
      return;
    }
    track.axis ??= dragAxis(dx, dy);
    if (track.axis === "x") {
      setDragging(true);
      setOffset({ x: dragOffset(dx, current, total), y: 0 });
    } else if (track.axis === "y") {
      setDragging(true);
      setOffset({ x: 0, y: Math.max(0, dy) });
    }
  };

  const endPointer = (event: ReactPointerEvent<HTMLDivElement>, cancelled: boolean) => {
    const track = pointerRef.current;
    if (!track || event.pointerId !== track.id) return;
    pointerRef.current = null;
    const dx = event.clientX - track.x;
    const dy = event.clientY - track.y;
    const ms = performance.now() - track.at;
    setDragging(false);
    if (cancelled) {
      setOffset({ x: 0, y: 0 });
      return;
    }
    if (zoom && track.axis) return;
    if (track.axis === "x") {
      const outcome = swipeOutcome({ dx, ms, width: track.width, index: current, total });
      if (outcome === "next") goTo(current + 1, dx);
      else if (outcome === "previous") goTo(current - 1, dx);
      else setOffset({ x: 0, y: 0 });
      return;
    }
    if (track.axis === "y") {
      setOffset({ x: 0, y: 0 });
      if (closesOnRelease(dy, ms)) onClose();
      return;
    }
    // A tap: a second one soon after makes it a double tap, which zooms - a
    // drawing that is there to zoom.
    if (tapTimer.current !== null) {
      window.clearTimeout(tapTimer.current);
      tapTimer.current = null;
      if (!currentPicture && !zoom) return;
      const fx = (event.clientX - track.left) / track.width;
      const fy = (event.clientY - track.top) / track.height;
      setArrowsShown(false);
      setZoom(zoom ? null : zoomOriginOffset(fx, fy, track.width, track.height));
      return;
    }
    tapTimer.current = window.setTimeout(() => {
      tapTimer.current = null;
      if (!phone || zoom) return;
      if (arrowsShown) setArrowsShown(false);
      else showArrowsForAWhile();
    }, DOUBLE_TAP_MS);
  };

  async function saveImage() {
    if (!entry || entry.available === false) return;
    try {
      const actions = decodeCanvasHistory(await loadBytes(entry));
      if (!actions) return;
      // Rendered to pixels of its own: the screen is never read (R-DRAW-19).
      const pixels = new Uint8ClampedArray(CANVAS_WIDTH * CANVAS_HEIGHT * 4);
      renderCanvasActionsUpTo(pixels, actions, { action: actions.length, point: 0 });
      void saveCanvasImage(pixels, entry.prompt);
    } catch {
      // The drawing on screen says it could not be loaded, with Try again.
    }
  }

  // The controls belong to one drawing: keyed by it, so nothing a control
  // holds - an open picker, a take-out waiting to be confirmed - carries over
  // to the next one, and built once per drawing rather than on every move of
  // a drag.
  const actions = useMemo(
    () => (entry ? <Fragment key={entryKey(entry)}>{renderActions?.(entry)}</Fragment> : null),
    [entry, renderActions],
  );
  const reactions = useMemo(
    () => (entry && renderReactions ? <Fragment key={entryKey(entry)}>{renderReactions(entry)}</Fragment> : null),
    [entry, renderReactions],
  );

  if (!entry || !currentEntry) return null;

  const previousEntry = slide
    ? (slide.direction < 0 ? entries[slide.to] : entries[current - 1])
    : entries[current - 1];
  const nextEntry = slide
    ? (slide.direction > 0 ? entries[slide.to] : entries[current + 1])
    : entries[current + 1];
  const still = dragging || instant;
  const trackTransform = slide
    ? `translate3d(${slide.direction > 0 ? "-66.6667%" : "0%"}, 0, 0)`
    : `translate3d(calc(-33.3333% + ${offset.x}px), 0, 0)`;
  const trackTransition = slide
    ? `transform ${slide.ms}ms cubic-bezier(0.2, 0.8, 0.2, 1)`
    : (still ? "none" : undefined);
  const dismissing = offset.y > 0 ? Math.min(offset.y, 300) : 0;
  const zoomTransform = zoom ? `translate(${zoom.x}px, ${zoom.y}px) scale(${ZOOM_SCALE})` : undefined;
  const paged = !phone && total > DESKTOP_STRIP_SIZE;
  const shownPicture = ready.get(entryKey(entry));

  return createPortal(
    <div
      ref={dialogRef}
      className={`drawing-viewer${phone ? " is-phone" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label={ui.drawingRecapGallery.drawingRecap}
      data-testid="drawing-viewer"
    >
      {/* Fades as a downward drag pulls the card away, so letting go closes
          what is visibly already leaving. */}
      <div
        className="drawing-viewer-backdrop"
        aria-hidden="true"
        style={dismissing ? { opacity: Math.max(0.35, 1 - dismissing / 400), transition: dragging ? "none" : undefined } : undefined}
      />
      {overviewOpen ? (
        <section className="drawing-viewer-overview" aria-labelledby="drawing-viewer-overview-title">
          <header className="drawing-viewer-overview-header">
            <button ref={backRef} type="button" className="btn btn-ghost drawing-viewer-back" onClick={closeOverview}>
              <ChevronLeftIcon size={18} />
              {ui.drawingRecapGallery.backToDrawing}
            </button>
            <h2 id="drawing-viewer-overview-title">{ui.drawingRecapGallery.allDrawings({ count: total })}</h2>
          </header>
          <ViewerOverview entries={entries} shown={shown} onPick={pickFromOverview} load={loadBytes} />
        </section>
      ) : (
        <>
          <div className="drawing-viewer-stage">
            {!phone && (
              <button
                type="button"
                className="drawing-viewer-arrow"
                aria-label={ui.drawingRecapGallery.previous}
                disabled={shown === 0}
                onClick={() => goTo(shown - 1)}
              >
                <ChevronLeftIcon size={26} strokeWidth={2.4} />
              </button>
            )}
            <section
              className="drawing-viewer-card"
              aria-labelledby="drawing-viewer-title"
              style={dismissing ? {
                transform: `translateY(${dismissing}px) scale(${(1 - dismissing / 1500).toFixed(3)})`,
                transition: dragging ? "none" : undefined,
              } : undefined}
            >
              <header className="drawing-viewer-header">
                <span aria-hidden="true" />
                <div className="drawing-viewer-title">
                  <h2 id="drawing-viewer-title">{entry.prompt}</h2>
                  <p className="drawing-viewer-byline">
                    {fill(ui.drawingRecapGallery.drawnBy, {
                      drawer: (
                        <strong
                          className={playerNameClass(entry.drawerIsAnonymous)}
                          style={playerNameStyle(entry.drawerNameColor, entry.drawerIsAnonymous)}
                        >
                          {entry.drawerNickname}
                        </strong>
                      ),
                    })}
                  </p>
                </div>
                <button
                  ref={closeRef}
                  type="button"
                  className="btn btn-icon drawing-viewer-close"
                  onClick={onClose}
                  aria-label={ui.drawingRecapGallery.closeDrawings}
                  data-skip-initial-focus
                >
                  <XIcon size={18} />
                </button>
              </header>

              <div className="drawing-viewer-figure">
                <div
                  ref={frameRef}
                  className="drawing-viewer-frame"
                  onPointerDown={onPointerDown}
                  onPointerMove={onPointerMove}
                  onPointerUp={(event) => endPointer(event, false)}
                  onPointerCancel={(event) => endPointer(event, true)}
                >
                  <div
                    className="drawing-viewer-track"
                    style={{ transform: trackTransform, transition: trackTransition }}
                  >
                    <ViewerSlide
                      key={previousEntry ? `previous:${entryKey(previousEntry)}` : "previous"}
                      target={previousEntry}
                      draw={drawImage}
                      ready={previousEntry ? ready.get(entryKey(previousEntry)) : undefined}
                    />
                    <ViewerSlide
                      key={`current:${entryKey(currentEntry)}`}
                      target={currentEntry}
                      draw={drawImage}
                      ready={currentPicture}
                      current
                      zoomTransform={zoomTransform}
                      animated={!still}
                    />
                    <ViewerSlide
                      key={nextEntry ? `next:${entryKey(nextEntry)}` : "next"}
                      target={nextEntry}
                      draw={drawImage}
                      ready={nextEntry ? ready.get(entryKey(nextEntry)) : undefined}
                    />
                  </div>
                  {phone && arrowsShown && !zoom && (
                    <>
                      <button
                        type="button"
                        className="drawing-viewer-arrow is-on-drawing is-previous"
                        aria-label={ui.drawingRecapGallery.previous}
                        disabled={shown === 0}
                        onClick={() => { showArrowsForAWhile(); goTo(shown - 1); }}
                      >
                        <ChevronLeftIcon size={20} strokeWidth={2.4} />
                      </button>
                      <button
                        type="button"
                        className="drawing-viewer-arrow is-on-drawing is-next"
                        aria-label={ui.drawingRecapGallery.next}
                        disabled={shown === total - 1}
                        onClick={() => { showArrowsForAWhile(); goTo(shown + 1); }}
                      >
                        <ChevronRightIcon size={20} strokeWidth={2.4} />
                      </button>
                    </>
                  )}
                </div>
                <div className={`drawing-viewer-tools${zoom || dragging ? " is-hidden" : ""}`}>
                  <div className="drawing-viewer-actions">
                    {actions}
                    <button
                      type="button"
                      className="btn btn-secondary btn-compact drawing-viewer-save"
                      aria-label={ui.drawingRecapGallery.saveImage}
                      title={ui.drawingRecapGallery.saveImage}
                      disabled={entry.available === false || !shownPicture}
                      onClick={() => void saveImage()}
                    >
                      <DownloadIcon size={16} />
                      <span className="drawing-viewer-tool-label" aria-hidden="true">
                        {ui.drawingRecapGallery.saveImage}
                      </span>
                    </button>
                  </div>
                  {reactions && <div className="drawing-viewer-reactions">{reactions}</div>}
                </div>
              </div>
              {entry.actionCount === 0 && entry.available !== false && (
                <p className="drawing-viewer-note">{ui.drawingRecapGallery.noDrawingWasCapturedThisTurn}</p>
              )}
            </section>
            {!phone && (
              <button
                type="button"
                className="drawing-viewer-arrow"
                aria-label={ui.drawingRecapGallery.next}
                disabled={shown === total - 1}
                onClick={() => goTo(shown + 1)}
              >
                <ChevronRightIcon size={26} strokeWidth={2.4} />
              </button>
            )}
          </div>

          <div className="drawing-viewer-strip">
            {paged && (
              <button
                type="button"
                className="drawing-viewer-page"
                aria-label={ui.drawingRecapGallery.earlierDrawings}
                disabled={stripStart === 0}
                onClick={() => setStripStart((start) => Math.max(0, start - DESKTOP_STRIP_SIZE))}
              >
                <ChevronsLeftIcon size={20} strokeWidth={2.4} />
              </button>
            )}
            <ViewerStrip
              entries={entries}
              start={phone ? 0 : stripStart}
              size={phone ? total : DESKTOP_STRIP_SIZE}
              shown={shown}
              onPick={pick}
              load={loadBytes}
              navRef={stripRef}
            />
            {paged && (
              <button
                type="button"
                className="drawing-viewer-page"
                aria-label={ui.drawingRecapGallery.laterDrawings}
                disabled={stripStart >= lastStripStart(total, DESKTOP_STRIP_SIZE)}
                onClick={() => setStripStart((start) =>
                  Math.min(lastStripStart(total, DESKTOP_STRIP_SIZE), start + DESKTOP_STRIP_SIZE))}
              >
                <ChevronsRightIcon size={20} strokeWidth={2.4} />
              </button>
            )}
          </div>
          {offersOverview(total) && (
            <button type="button" className="drawing-viewer-all" onClick={() => setOverviewOpen(true)}>
              <GridIcon size={15} />
              {ui.drawingRecapGallery.allDrawings({ count: total })}
            </button>
          )}
          <p className="visually-hidden" aria-live="polite">
            {`${entryLabel(entry)}. ${ui.drawingRecapGallery.position({ position: shown + 1, total })}`}
          </p>
        </>
      )}
    </div>,
    document.body,
  );
}

/** One thumbnail: a button that brings its drawing up. */
function ViewerThumb({
  target,
  position,
  current,
  onPick,
  load,
}: {
  target: DrawingRecapMetadata;
  position: number;
  current: boolean;
  onPick: (position: number) => void;
  load: (entry: DrawingRecapMetadata) => Promise<ArrayBuffer>;
}) {
  return (
    <button
      type="button"
      className="drawing-viewer-thumb"
      aria-current={current ? "true" : undefined}
      aria-label={entryLabel(target)}
      onClick={() => onPick(position)}
    >
      {target.available === false ? (
        <span className="drawing-viewer-thumb-note">
          {target.removed ? ui.drawingRecapGallery.removed : ui.drawingRecapGallery.notKept}
        </span>
      ) : (
        <DrawingThumbnail
          drawingKey={entryKey(target)}
          load={() => load(target)}
          label=""
          className="drawing-viewer-thumb-image"
          noteClassName="drawing-viewer-thumb-note"
          failedText={ui.drawingRecapGallery.notAvailable}
        />
      )}
    </button>
  );
}

/** The strip: a page of thumbnails on a desktop, all of them on a phone. Its
    own component, held still while a drag re-renders the viewer: up to 160
    thumbnails need not follow every pointer move. */
const ViewerStrip = memo(function ViewerStrip({
  entries,
  start,
  size,
  shown,
  onPick,
  load,
  navRef,
}: {
  entries: DrawingRecapMetadata[];
  start: number;
  size: number;
  shown: number;
  onPick: (position: number) => void;
  load: (entry: DrawingRecapMetadata) => Promise<ArrayBuffer>;
  navRef: RefObject<HTMLElement | null>;
}) {
  return (
    <nav ref={navRef} className="drawing-viewer-thumbs" aria-label={ui.drawingRecapGallery.drawingRecapNavigation}>
      {entries.slice(start, start + size).map((target, offset) => (
        <ViewerThumb
          key={entryKey(target)}
          target={target}
          position={start + offset}
          current={start + offset === shown}
          onPick={onPick}
          load={load}
        />
      ))}
    </nav>
  );
});

/** Every drawing of the game, by round. */
function ViewerOverview({
  entries,
  shown,
  onPick,
  load,
}: {
  entries: DrawingRecapMetadata[];
  shown: number;
  onPick: (position: number) => void;
  load: (entry: DrawingRecapMetadata) => Promise<ArrayBuffer>;
}) {
  const rounds: { round: number; items: { target: DrawingRecapMetadata; position: number }[] }[] = [];
  entries.forEach((target, position) => {
    const last = rounds[rounds.length - 1];
    if (last && last.round === target.roundNumber) last.items.push({ target, position });
    else rounds.push({ round: target.roundNumber, items: [{ target, position }] });
  });
  return (
    <div className="drawing-viewer-overview-body">
      {rounds.map((group) => (
        <section key={group.round} className="drawing-viewer-overview-round">
          <h3 className="section-label">{ui.drawingRecapGallery.round({ round: group.round })}</h3>
          <div className="drawing-viewer-overview-grid">
            {group.items.map(({ target, position }) => (
              <ViewerThumb
                key={entryKey(target)}
                target={target}
                position={position}
                current={position === shown}
                onPick={onPick}
                load={load}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** One slot of the track: the drawing at its full size from the viewer's
    picture cache, or why there is none to show. Keyed by its drawing, so a
    slot that already has its picture shows it on the first frame. Only the
    middle slot is read out; the two beside it are off screen. */
const ViewerSlide = memo(function ViewerSlide({
  target,
  draw,
  ready,
  current = false,
  zoomTransform,
  animated = true,
}: {
  target: DrawingRecapMetadata | undefined;
  draw: (entry: DrawingRecapMetadata) => Promise<string>;
  ready: string | undefined;
  current?: boolean;
  zoomTransform?: string;
  animated?: boolean;
}) {
  const [drawn, setDrawn] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const unavailable = target?.available === false;
  const src = ready ?? drawn;

  useEffect(() => {
    if (!target || unavailable || src) return;
    let live = true;
    draw(target).then(
      (url) => {
        if (live) setDrawn(url);
      },
      (failure) => {
        if (live) setError(socketRequestErrorMessage(failure, ui.drawingRecapGallery.loadThisDrawing));
      },
    );
    return () => {
      live = false;
    };
    // Keyed by its drawing, so `target` only changes with `attempt`; a
    // picture let go while the slot shows it is drawn again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt, unavailable, src]);

  const className = `drawing-viewer-slide${current ? " is-current" : ""}`;
  const hidden = current ? undefined : true;
  if (!target) return <div className={className} aria-hidden="true" />;
  if (unavailable) {
    return (
      <div className={className} aria-hidden={hidden}>
        <div className="drawing-viewer-status">
          {target.removed ? (
            <p>{ui.drawingRecapGallery.removedByModeration}</p>
          ) : (
            <>
              <p>{ui.drawingRecapGallery.thisDrawingWasNotKept}</p>
              <p className="drawing-viewer-status-detail">{ui.drawingRecapGallery.earlierDrawingsFilledTheSpace}</p>
            </>
          )}
        </div>
      </div>
    );
  }
  if (error && !src) {
    return (
      <div className={className} aria-hidden={hidden}>
        <div className="drawing-viewer-status" role={current ? "alert" : undefined}>
          <p>{error}</p>
          {current && (
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              onClick={() => {
                setError(null);
                setAttempt((count) => count + 1);
              }}
            >
              {ui.drawingRecapGallery.tryAgain}
            </button>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className={className} aria-hidden={hidden} aria-busy={src ? undefined : true}>
      {src ? (
        <img
          src={src}
          alt={current ? entryLabel(target) : ""}
          draggable={false}
          decoding="async"
          style={{
            transform: current ? zoomTransform : undefined,
            transition: current && !animated ? "none" : undefined,
          }}
        />
      ) : (
        <span className="visually-hidden">{ui.drawingRecapGallery.loadingDrawing}</span>
      )}
    </div>
  );
});
