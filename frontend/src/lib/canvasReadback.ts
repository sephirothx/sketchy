/** Whether this browser hands back the pixels the game painted.

The canvas is painted by reading a region back, changing some pixels and
writing it back (`canvasRenderer.ts`), and a fill reads the whole canvas. Some
privacy protections answer a read with other pixels than the ones on the
canvas, so that a page cannot fingerprint the machine by what it renders.
Firefox's `privacy.resistFingerprinting` - on by default in Tor Browser,
Mullvad Browser and LibreWolf - answers with noise, and the game wrote that
noise back: every stroke landed in a rectangle of coloured static, on the
drawer's canvas and on every viewer's with the setting (measured 2026-09-19).
A page cannot read or change browser settings, so the game says so and says
what to do (**Canvas blocked**, R-UX-15).

The probe paints a known pattern on a canvas of its own and reads it back.
It looks for the effect, not the setting, so any browser or extension that
does the same is caught too. Brave perturbs a read by one step on a channel,
which no one can see and which the fill's own tolerance already absorbs, so a
difference is only tampering past `READBACK_TOLERANCE` - the same margin a
fill allows (`FLOOD_FILL_CHANNEL_TOLERANCE`). */

import { FLOOD_FILL_CHANNEL_TOLERANCE } from "./canvasPixels.ts";

export type CanvasReadback = "unknown" | "ok" | "tampered";

export const READBACK_TOLERANCE = FLOOD_FILL_CHANNEL_TOLERANCE;
export const PROBE_SIZE = 16;

/** Opaque pixels of many values, so that no answer made of one colour -
white, black, or whatever a protection substitutes - can match it. */
export function probePattern(size: number = PROBE_SIZE): Uint8ClampedArray {
  const data = new Uint8ClampedArray(size * size * 4);
  for (let pixel = 0; pixel < size * size; pixel++) {
    data[pixel * 4] = (pixel * 37) % 256;
    data[pixel * 4 + 1] = (pixel * 91 + 64) % 256;
    data[pixel * 4 + 2] = (pixel * 173 + 128) % 256;
    data[pixel * 4 + 3] = 255;
  }
  return data;
}

/** Whether `read` differs from `written` by more than `tolerance` on any channel. */
export function readbackTampered(
  written: ArrayLike<number>,
  read: ArrayLike<number>,
  tolerance: number = READBACK_TOLERANCE,
): boolean {
  if (written.length !== read.length) return true;
  for (let index = 0; index < written.length; index++) {
    if (Math.abs(written[index] - read[index]) > tolerance) return true;
  }
  return false;
}

interface ProbeContext {
  createImageData(width: number, height: number): { data: Uint8ClampedArray };
  putImageData(image: never, x: number, y: number): void;
  getImageData(x: number, y: number, width: number, height: number): { data: Uint8ClampedArray };
}

/** Paint the pattern on `context` and read it back. "unknown" when the
browser has no 2D canvas or refuses the read outright. */
export function probeCanvasReadback(context: ProbeContext | null): CanvasReadback {
  if (!context) return "unknown";
  try {
    const image = context.createImageData(PROBE_SIZE, PROBE_SIZE);
    const pattern = probePattern();
    image.data.set(pattern);
    context.putImageData(image as never, 0, 0);
    const read = context.getImageData(0, 0, PROBE_SIZE, PROBE_SIZE).data;
    return readbackTampered(pattern, read) ? "tampered" : "ok";
  } catch {
    return "unknown";
  }
}

/** The probe on a canvas made for it, never shown. */
export function checkCanvasReadback(): CanvasReadback {
  if (typeof document === "undefined") return "unknown";
  const canvas = document.createElement("canvas");
  canvas.width = PROBE_SIZE;
  canvas.height = PROBE_SIZE;
  return probeCanvasReadback(canvas.getContext("2d", { willReadFrequently: true }));
}
