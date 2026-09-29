import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import { inflateSync } from "node:zlib";

import { CANVAS_HEIGHT, CANVAS_WIDTH, decodeCanvasHistory } from "../src/lib/canvasHistory.ts";
import { renderCanvasActions } from "../src/lib/canvasRenderer.ts";
import { downscalePixels } from "../src/lib/canvasThumbnail.ts";
import { encodePng } from "../src/lib/pngEncode.ts";
import { renderThumbnail, thumbnailSize } from "../src/lib/thumbnailRender.ts";

/** The accepted 100-fill turn (#1282), regenerated and pinned by the backend. */
const fixture = JSON.parse(readFileSync(new URL("../../fixtures/fill_replay_100.json", import.meta.url), "utf8"));
const fillHeavy = Uint8Array.from(Buffer.from(fixture.base64, "base64")).buffer;

/** What `DrawingThumbnail` did on the page before #1282, kept as the reference. */
async function pagePipeline(bytes, pixelWidth) {
  const actions = decodeCanvasHistory(bytes);
  const pixels = new Uint8ClampedArray(CANVAS_WIDTH * CANVAS_HEIGHT * 4);
  renderCanvasActions({ pixels, commit: () => undefined }, actions);
  const width = Math.max(1, Math.min(CANVAS_WIDTH, Math.round(pixelWidth)));
  const height = Math.max(1, Math.round((width * CANVAS_HEIGHT) / CANVAS_WIDTH));
  const small = width === CANVAS_WIDTH ? pixels.slice() : downscalePixels(pixels, CANVAS_WIDTH, CANVAS_HEIGHT, width, height);
  return { png: await encodePng(small, width, height), width, height };
}

test("the fill-heavy fixture decodes to the hundred fills the server accepted", () => {
  const actions = decodeCanvasHistory(fillHeavy);
  assert.equal(actions.length, fixture.actions);
  assert.ok(actions.every((action) => action.kind === "fill"));
});

test("a thumbnail is the same image, byte for byte, wherever it is drawn", async () => {
  // The worker runs `renderThumbnail`; the page ran the pipeline above.
  const drawn = await renderThumbnail(fillHeavy, 320);
  const reference = await pagePipeline(fillHeavy, 320);
  assert.equal(drawn.width, 320);
  assert.equal(drawn.height, 240);
  assert.deepEqual(drawn.png, reference.png);
});

test("full width keeps every pixel, and the staging buffer is reused cleanly", async () => {
  const first = await renderThumbnail(fillHeavy, 800);
  const again = await renderThumbnail(fillHeavy, 800);
  assert.deepEqual(first.png, again.png);
  assert.equal(first.width, 800);
});

test("a history that does not decode is no image, not an exception", async () => {
  assert.equal(await renderThumbnail(new Uint8Array([1, 2, 3]).buffer, 200), null);
});

test("sizes stay inside the drawing and never reach zero", () => {
  assert.deepEqual(thumbnailSize(64), { width: 64, height: 48 });
  assert.deepEqual(thumbnailSize(5000), { width: 800, height: 600 });
  assert.deepEqual(thumbnailSize(0), { width: 400, height: 300 });
  assert.deepEqual(thumbnailSize(0.2), { width: 1, height: 1 });
});

/** A PNG's header and its inflated scanlines: the image itself. The
compressed bytes are `CompressionStream`'s, and its deflate differs between
platforms - CI's Linux runner and a Mac encode the same pixels differently -
so a pin on them fails for a reason that is not the picture. */
function imageOf(png) {
  const view = new DataView(png.buffer, png.byteOffset, png.byteLength);
  let offset = 8;
  let header;
  const data = [];
  while (offset < png.length) {
    const length = view.getUint32(offset);
    const type = String.fromCharCode(...png.subarray(offset + 4, offset + 8));
    const body = Buffer.from(png.subarray(offset + 8, offset + 8 + length));
    if (type === "IHDR") header = body;
    if (type === "IDAT") data.push(body);
    offset += 12 + length;
  }
  return Buffer.concat([header, inflateSync(Buffer.concat(data))]);
}

test("thumbnails are main's images, pixel for pixel, pinned at a size that is not a whole factor", async () => {
  // Hashes of the images main's on-page pipeline encoded before #1282, at
  // 333 px - a scale the box filter has to average unevenly. The fill fixture
  // is one flat colour; `width-runs` is strokes of changing width, where a
  // scaling difference would show.
  const protocol = JSON.parse(readFileSync(new URL("../../fixtures/canvas_protocol_v1.json", import.meta.url), "utf8"));
  const widthRuns = Uint8Array.from(
    protocol.histories.find((history) => history.name === "width-runs").binary.match(/../g),
    (byte) => Number.parseInt(byte, 16),
  ).buffer;
  const pinned = [
    [widthRuns, "831473e2f68998176ed0f088e7520cf0290a2002583966b54a319c24ab625899"],
    [fillHeavy, "5965b99f8514d3f05187809130e5cc30e293b5a34c268f1b61b794602468ba73"],
  ];
  for (const [bytes, digest] of pinned) {
    const drawn = await renderThumbnail(bytes, 333);
    assert.equal(createHash("sha256").update(imageOf(drawn.png)).digest("hex"), digest);
  }
});

test("the worker answers with the PNG transferred, not copied", async () => {
  const sent = [];
  let answered;
  const done = new Promise((resolve) => { answered = resolve; });
  globalThis.self = {
    onmessage: null,
    postMessage(message, transfer) {
      sent.push({ message, transfer });
      answered();
    },
  };
  try {
    await import("../src/workers/thumbnail.worker.ts");
    globalThis.self.onmessage({ data: { id: 7, bytes: fillHeavy.slice(0), pixelWidth: 320 } });
    await done;
  } finally {
    delete globalThis.self;
  }
  const [{ message, transfer }] = sent;
  const reference = await renderThumbnail(fillHeavy, 320);
  assert.equal(message.id, 7);
  assert.equal(message.width, 320);
  assert.ok(message.png instanceof ArrayBuffer);
  assert.deepEqual(new Uint8Array(message.png), reference.png);
  assert.deepEqual(transfer, [message.png], "the buffer is handed over, not cloned");
});
