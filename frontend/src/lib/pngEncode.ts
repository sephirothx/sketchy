/** A PNG of the drawing, encoded from its pixels rather than read off the canvas.

**Save image** used to be `canvas.toDataURL()`, which is a canvas read like
any other: a browser that scrambles reads (`canvasSurface.ts`) saved the
scrambled picture. The drawing's own pixels are right, so the file is made
from those. Every pixel is opaque, so it is RGB, eight bits a channel, rows
unfiltered - a drawing is mostly flat colour, which deflate takes care of.

Compression is the browser's own (`CompressionStream("deflate")`, which is the
zlib format a PNG wants). Where that is missing the data goes in stored
blocks: a larger file, never a failed save. */

const SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + data.length);
  const view = new DataView(out.buffer);
  view.setUint32(0, data.length);
  for (let index = 0; index < 4; index++) out[4 + index] = type.charCodeAt(index);
  out.set(data, 8);
  view.setUint32(8 + data.length, crc32(out.subarray(4, 8 + data.length)));
  return out;
}

/** The scanlines: a filter byte of 0, then each pixel's red, green and blue. */
export function scanlines(pixels: Uint8ClampedArray, width: number, height: number): Uint8Array {
  const stride = 1 + width * 3;
  const raw = new Uint8Array(stride * height);
  for (let y = 0; y < height; y++) {
    let to = y * stride + 1;
    let from = y * width * 4;
    for (let x = 0; x < width; x++, from += 4) {
      raw[to++] = pixels[from];
      raw[to++] = pixels[from + 1];
      raw[to++] = pixels[from + 2];
    }
  }
  return raw;
}

function adler32(bytes: Uint8Array): number {
  let a = 1;
  let b = 0;
  for (let index = 0; index < bytes.length; index += 5552) {
    const end = Math.min(bytes.length, index + 5552);
    for (let at = index; at < end; at++) {
      a += bytes[at];
      b += a;
    }
    a %= 65521;
    b %= 65521;
  }
  return ((b << 16) | a) >>> 0;
}

/** zlib with uncompressed ("stored") deflate blocks. */
export function storedZlib(raw: Uint8Array): Uint8Array {
  const blocks = Math.max(1, Math.ceil(raw.length / 65535));
  const out = new Uint8Array(2 + raw.length + blocks * 5 + 4);
  out[0] = 0x78;
  out[1] = 0x01;
  let at = 2;
  for (let block = 0; block < blocks; block++) {
    const start = block * 65535;
    const length = Math.min(65535, raw.length - start);
    out[at] = block === blocks - 1 ? 1 : 0;
    out[at + 1] = length & 0xff;
    out[at + 2] = length >>> 8;
    out[at + 3] = ~length & 0xff;
    out[at + 4] = (~length >>> 8) & 0xff;
    out.set(raw.subarray(start, start + length), at + 5);
    at += 5 + length;
  }
  new DataView(out.buffer).setUint32(at, adler32(raw));
  return out;
}

async function zlib(raw: Uint8Array): Promise<Uint8Array> {
  if (typeof CompressionStream === "undefined") return storedZlib(raw);
  try {
    const stream = new Blob([raw as BlobPart]).stream().pipeThrough(new CompressionStream("deflate"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch {
    return storedZlib(raw);
  }
}

export async function encodePng(pixels: Uint8ClampedArray, width: number, height: number): Promise<Uint8Array> {
  const header = new Uint8Array(13);
  const view = new DataView(header.buffer);
  view.setUint32(0, width);
  view.setUint32(4, height);
  header[8] = 8; // bits per channel
  header[9] = 2; // RGB
  const parts = [
    Uint8Array.from(SIGNATURE),
    chunk("IHDR", header),
    chunk("IDAT", await zlib(scanlines(pixels, width, height))),
    chunk("IEND", new Uint8Array(0)),
  ];
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}
