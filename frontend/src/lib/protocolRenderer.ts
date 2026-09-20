/** The renderer behind a canvas: frames in, pixels out (#886 moved it here).

Its own module rather than the component's, because what it holds - a
playback queue, an animation frame, a `visibilitychange` listener - outlives
a render and has to be given back on unmount, and because that is only
testable outside a `.tsx`.
*/
import type { RefObject } from "react";

import type { CanvasProtocolRenderer } from "../hooks/useCanvasProtocol.ts";
import type { DecodedCanvasAction } from "./canvasHistory.ts";
import { toPixels } from "./canvasGeometry.ts";
import type { Point } from "./canvasGeometry.ts";
import { hexToRgba } from "./canvasPixels.ts";
import {
  applyFillAction,
  drawShapeOutlinePixels,
  fillWhite,
  rasterizePolyline,
  rasterizeSegmentSpans,
  renderCanvasActions,
} from "./canvasRenderer.ts";
import type { LiveDrawingPacket } from "./liveDrawing.ts";
import { currentClientConfig } from "./clientConfig.ts";
import { finalWidth, rampedBatch } from "./pathWidths.ts";
import { createStrokePlayback } from "./strokePlayback.ts";
import type { CanvasSurface } from "./canvasSurface.ts";

export function createProtocolRenderer(
  surfaceRef: RefObject<CanvasSurface | null>,
  // Where the hidden-tab listener goes. Passed in so a test can count what a
  // mount adds and a `dispose` takes back (#886); the component passes none
  // and it goes on the document, as it always has.
  listeners: Pick<Document, "addEventListener" | "removeEventListener"> | null =
    typeof document === "undefined" ? null : document,
): CanvasProtocolRenderer {
  // Where the open path ends *as queued*, in canvas pixels, and the style
  // it is drawn in. Updated the moment a frame is queued, never inside a
  // deferred barrier: a batch joins the point queued before it, and reading
  // the state a barrier will set later would anchor a new stroke's first
  // batch to the previous stroke's end while that end is still playing.
  const queued: { last: Point | null; color: string; width: number } = {
    last: null,
    color: "#000000",
    width: 4,
  };

  // Received points are played out over the flush interval that follows
  // them rather than painted the moment they land (#559): what is on screen
  // advances at the animation rate, while the history and the commits behind
  // it were applied synchronously by the protocol hook before `apply` was
  // called. Everything that is not a run of points is a barrier in the same
  // queue, so nothing is painted out of order.
  const playback = createStrokePlayback({
    intervalMs: () => currentClientConfig().flushIntervalMs,
    // Spans of the received segments rather than the interpolated polyline,
    // so a stroke played out a frame at a time ends as the pixels the drawer
    // and every replay have (#940).
    paint: (_points, style, spans) => {
      const surface = surfaceRef.current;
      if (surface) rasterizeSegmentSpans(surface, spans, style.radius, style.color);
    },
  });
  let frame: number | null = null;
  const tick = () => {
    frame = null;
    if (playback.advance(performance.now())) frame = window.requestAnimationFrame(tick);
  };
  const schedule = () => {
    if (frame === null && playback.pending()) frame = window.requestAnimationFrame(tick);
  };
  const stopTicking = () => {
    if (frame !== null) window.cancelAnimationFrame(frame);
    frame = null;
  };
  // A hidden tab gets no animation frames; drain rather than hold ink
  // for as long as it is away, so what it shows on return is current.
  const onVisibilityChange = () => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      playback.drain();
    }
  };
  listeners?.addEventListener("visibilitychange", onVisibilityChange);

  const clear = () => {
    playback.cancel();
    stopTicking();
    const surface = surfaceRef.current;
    if (surface) fillWhite(surface);
    queued.last = null;
  };

  const apply = (packet: LiveDrawingPacket) => {
    const context = surfaceRef.current;
    if (!context) return;
    const now = performance.now();
    if (packet.event === "draw_start") {
      const { x, y, color, width } = packet.payload;
      const point = toPixels({ x, y });
      queued.last = point;
      queued.color = color;
      queued.width = width;
      playback.enqueueBarrier(() => {
        rasterizePolyline(context, [point, point], width / 2, hexToRgba(color));
      }, now);
    } else if (packet.event === "draw_move") {
      // No open path to join - the start never arrived on this connection
      // and the replay did not leave one open - is nothing to paint from;
      // the history has the points, and the next resync will show them.
      if (packet.payload.points.length === 0 || !queued.last) return;
      const style = { radius: queued.width / 2, color: hexToRgba(queued.color) };
      const points = packet.payload.points.map(toPixels);
      // A pen may have changed the width inside the batch (#828): ramped, as
      // every painter ramps it, and the next batch carries on at whatever
      // this one ended at.
      const batch = rampedBatch(queued.last, points, queued.width, packet.payload.widths);
      playback.enqueueSegments(
        queued.last,
        batch.points,
        style,
        now,
        batch.segmentWidths.map((width) => width / 2),
      );
      queued.width = batch.finalWidth;
      queued.last = packet.payload.ends ? null : points[points.length - 1];
    } else if (packet.event === "draw_end") {
      queued.last = null;
    } else if (packet.event === "draw_shape") {
      const payload = packet.payload;
      playback.enqueueBarrier(() => {
        drawShapeOutlinePixels(
          context,
          payload.from,
          payload.to,
          payload.shape,
          payload.color,
          payload.width,
        );
      }, now);
    } else if (packet.event === "draw_fill") {
      // A fill must see the complete raster before it: a barrier, so every
      // queued point is painted first.
      const payload = packet.payload;
      playback.enqueueBarrier(() => {
        applyFillAction(context, payload);
      }, now);
    } else if (packet.event === "clear_canvas") {
      clear();
    }
    // `draw_move_relative` never reaches here: the protocol hook resolves it
    // against the history before it is painted (#559).
    schedule();
  };

  const replay = (actions: DecodedCanvasAction[]) => {
    // What was queued is inside the history being repainted, or superseded
    // by it; either way it must not land on top afterwards.
    playback.cancel();
    stopTicking();
    // Straight into the drawing, shown once at the end: it overwrites every
    // pixel, so nothing stale carries over, and it never reads the canvas.
    const surface = surfaceRef.current;
    if (surface) renderCanvasActions(surface, actions);
    // A replay that ends on a path may have landed mid-stroke: the live
    // batches that follow join that path's last point. If the path was in
    // fact closed, the next frame is a start and resets this anyway.
    const last = actions.at(-1);
    const end = last?.kind === "path" ? last.points.at(-1) : undefined;
    if (last?.kind === "path" && end) {
      queued.last = { x: end.x, y: end.y };
      queued.color = last.color;
      queued.width = finalWidth(last.width, last.widths);
    } else {
      queued.last = null;
    }
  };

  const dispose = () => {
    listeners?.removeEventListener("visibilitychange", onVisibilityChange);
    playback.cancel();
    stopTicking();
  };

  return { apply, clear, replay, dispose };
}
