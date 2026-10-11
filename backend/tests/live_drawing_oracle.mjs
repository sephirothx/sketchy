// The client's live-drawing decoder as a line-oriented process, for
// `test_live_drawing_differential.py` (#1464).
//
// One JSON array of requests per line on stdin, one JSON array of answers per
// line on stdout, so a single Node process serves every generated frame instead
// of one process per frame, and one round trip covers every shape of a frame.
// A request names the frame in the shape it would cross the wire in - `hex`
// (bytes, as a `Uint8Array`), `buffer` (the same bytes as the `ArrayBuffer`
// socket.io-client delivers), `b64` (the base64 string small frames travel as)
// or `int` (a bare control byte) - and `previous`, the open path's last point that
// a relative frame resolves against. The answer is the decoded packet in the
// same normalized shape the Python side builds, or null for a refused frame.
//
// It imports `frontend/src/lib/liveDrawing.ts` directly: that module and the
// two it imports have no package dependencies, so this runs without
// `node_modules` - which is what lets the backend CI job run it.

import { createInterface } from "node:readline";

// stdout carries the answers and nothing else: a stray log line in the decoder
// would otherwise be read as one, and every answer after it misaligned.
console.log = console.info = console.debug = (...args) => console.error(...args);

const { decodeLiveDrawing } = await import("../../frontend/src/lib/liveDrawing.ts");

function point(value) {
  return [value.x, value.y];
}

function normalize(packet) {
  if (packet === null) return null;
  const out = { event: packet.event };
  for (const [key, value] of Object.entries(packet.payload)) {
    if (key === "points") out.points = value.map(point);
    else if (key === "from" || key === "to") out[key] = point(value);
    else out[key] = value;
  }
  return out;
}

function decode(request) {
  let frame;
  if ("hex" in request) frame = Uint8Array.from(Buffer.from(request.hex, "hex"));
  else if ("buffer" in request) frame = Uint8Array.from(Buffer.from(request.buffer, "hex")).buffer;
  else if ("b64" in request) frame = request.b64;
  else frame = request.int;
  const previous = request.previous ? { x: request.previous[0], y: request.previous[1] } : null;
  try {
    return { result: normalize(decodeLiveDrawing(frame, previous)) };
  } catch (error) {
    // A decoder that throws instead of refusing is a finding of its own: in a
    // viewer it is an exception inside a socket event handler.
    return { threw: String(error) };
  }
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line) continue;
  process.stdout.write(`${JSON.stringify(JSON.parse(line).map(decode))}\n`);
}
