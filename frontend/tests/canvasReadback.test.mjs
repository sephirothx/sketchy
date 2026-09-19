import assert from "node:assert/strict";
import test from "node:test";

import {
  PROBE_SIZE,
  READBACK_TOLERANCE,
  probeCanvasReadback,
  probePattern,
  readbackTampered,
} from "../src/lib/canvasReadback.ts";

/** A context whose reads return what was written, passed through `alter`. */
function context(alter = (data) => data) {
  let stored = new Uint8ClampedArray(PROBE_SIZE * PROBE_SIZE * 4);
  return {
    createImageData: (width, height) => ({ data: new Uint8ClampedArray(width * height * 4) }),
    putImageData: (image) => { stored = new Uint8ClampedArray(image.data); },
    getImageData: () => ({ data: alter(new Uint8ClampedArray(stored)) }),
  };
}

test("a browser that reads back what it painted is ok", () => {
  assert.equal(probeCanvasReadback(context()), "ok");
});

test("Brave's one-step perturbation is not tampering: nobody can see it, and a fill absorbs it", () => {
  const brave = (data) => data.map((value, index) => (index % 4 === 3 ? value : index % 7 === 0 ? Math.max(0, value - 1) : value));
  assert.equal(probeCanvasReadback(context(brave)), "ok");
  assert.equal(READBACK_TOLERANCE, 8);
});

test("resistFingerprinting's noise is tampering, and so is a read that comes back one colour", () => {
  let seed = 7;
  const noise = (data) => data.map((value, index) => (index % 4 === 3 ? 255 : (seed = (seed * 1103515245 + 12345) % 2147483648) % 256));
  assert.equal(probeCanvasReadback(context(noise)), "tampered");
  assert.equal(probeCanvasReadback(context((data) => data.fill(255))), "tampered");
  assert.equal(probeCanvasReadback(context((data) => data.map((value, index) => (index % 4 === 3 ? 255 : 0)))), "tampered");
});

test("the margin is the fill's: eight steps pass, nine do not", () => {
  const pattern = probePattern();
  const shifted = (by) => pattern.map((value, index) => (index === 0 ? Math.min(255, value + by) : value));
  assert.equal(pattern[0] + 9 <= 255, true);
  assert.equal(readbackTampered(pattern, shifted(8)), false);
  assert.equal(readbackTampered(pattern, shifted(9)), true);
});

test("no canvas, or a read refused outright, is unknown rather than a warning", () => {
  assert.equal(probeCanvasReadback(null), "unknown");
  const refusing = { ...context(), getImageData: () => { throw new Error("SecurityError"); } };
  assert.equal(probeCanvasReadback(refusing), "unknown");
});
