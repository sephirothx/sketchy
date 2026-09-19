import assert from "node:assert/strict";
import test from "node:test";
import { crc32, inflateSync } from "node:zlib";

import { encodePng, scanlines, storedZlib } from "../src/lib/pngEncode.ts";

/** Chunks of a PNG, with their CRCs checked. */
function chunks(png) {
  assert.deepEqual([...png.subarray(0, 8)], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const view = new DataView(png.buffer, png.byteOffset, png.byteLength);
  const out = [];
  for (let at = 8; at < png.length;) {
    const length = view.getUint32(at);
    const type = String.fromCharCode(...png.subarray(at + 4, at + 8));
    const data = png.subarray(at + 8, at + 8 + length);
    assert.equal(view.getUint32(at + 8 + length), crc32(png.subarray(at + 4, at + 8 + length)), `${type} CRC`);
    out.push({ type, data });
    at += 12 + length;
  }
  return out;
}

function drawing(width, height) {
  const pixels = new Uint8ClampedArray(width * height * 4);
  for (let index = 0; index < width * height; index++) {
    pixels.set([(index * 7) % 256, (index * 13) % 256, (index * 29) % 256, 255], index * 4);
  }
  return pixels;
}

test("Save image is a PNG of the drawing's own pixels, not a canvas read", async () => {
  const width = 37;
  const height = 11;
  const pixels = drawing(width, height);
  const parts = chunks(await encodePng(pixels, width, height));
  assert.deepEqual(parts.map((part) => part.type), ["IHDR", "IDAT", "IEND"]);
  const header = new DataView(parts[0].data.buffer, parts[0].data.byteOffset);
  assert.deepEqual([header.getUint32(0), header.getUint32(4), parts[0].data[8], parts[0].data[9]], [width, height, 8, 2]);
  const raw = inflateSync(parts[1].data);
  assert.deepEqual(new Uint8Array(raw), scanlines(pixels, width, height));
  // Every row unfiltered, then the pixel's red, green and blue.
  assert.equal(raw[0], 0);
  assert.deepEqual([...raw.subarray(1, 4)], [...pixels.subarray(0, 3)]);
});

test("without the browser's compressor the data goes in stored blocks, a valid zlib stream", () => {
  // Past one block's 65 535 bytes, so the block boundary is exercised.
  const raw = scanlines(drawing(200, 120), 200, 120);
  assert.ok(raw.length > 65535);
  assert.deepEqual(new Uint8Array(inflateSync(storedZlib(raw))), raw);
  assert.deepEqual(new Uint8Array(inflateSync(storedZlib(new Uint8Array(0)))), new Uint8Array(0));
});
