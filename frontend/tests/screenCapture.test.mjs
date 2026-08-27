import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

import { MAX_EDGE, canCaptureScreen, captureScreenshot } from "../src/lib/screenCapture.ts";

/** A browser only as far as this module reaches into one. */
function stubBrowser({ getDisplayMedia, videoSize = { width: 3840, height: 2160 } } = {}) {
  const stopped = [];
  const drawn = [];
  globalThis.navigator = getDisplayMedia
    ? { mediaDevices: { getDisplayMedia } }
    : { mediaDevices: {} };
  globalThis.DOMException = globalThis.DOMException ?? class extends Error {};
  globalThis.requestAnimationFrame = (callback) => callback();
  globalThis.btoa = (binary) => Buffer.from(binary, "binary").toString("base64");
  globalThis.URL = { createObjectURL: () => "blob:preview" };
  globalThis.document = {
    createElement(tag) {
      if (tag === "video") {
        return {
          srcObject: null,
          muted: false,
          videoWidth: videoSize.width,
          videoHeight: videoSize.height,
          play: async () => {},
          pause() {},
        };
      }
      return {
        width: 0,
        height: 0,
        getContext: () => ({ drawImage: (_source, _x, _y, w, h) => drawn.push({ w, h }) }),
        toBlob(callback, type) {
          callback({
            type: type ?? "image/png",
            size: 1024,
            arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer,
          });
        },
      };
    },
  };
  return { stopped, drawn };
}

function aStream(stopped) {
  return { getTracks: () => [{ stop: () => stopped.push("a") }, { stop: () => stopped.push("b") }] };
}

beforeEach(() => {
  delete globalThis.navigator;
  delete globalThis.document;
});

test("a browser without getDisplayMedia is reported as unable, not broken", async () => {
  stubBrowser();
  assert.equal(canCaptureScreen(), false);
  // The dialog leaves the button out; asking anyway must still be harmless.
  assert.equal(await captureScreenshot(), null);
});

test("cancelling the picker is an answer, not an error", async () => {
  const { stopped } = stubBrowser({
    // The real DOMException takes its name at construction; it is read-only.
    getDisplayMedia: async () => {
      throw new DOMException("Permission denied", "NotAllowedError");
    },
  });
  assert.equal(await captureScreenshot(), null);
  assert.deepEqual(stopped, []);
});

test("a captured frame is scaled down to the long-edge limit", async () => {
  const stopped = [];
  const { drawn } = stubBrowser({ getDisplayMedia: async () => aStream(stopped) });
  const shot = await captureScreenshot();
  assert.equal(Math.max(shot.width, shot.height), MAX_EDGE);
  // 3840x2160 keeps its aspect ratio at 1600x900.
  assert.deepEqual([shot.width, shot.height], [MAX_EDGE, 900]);
  assert.deepEqual(drawn, [{ w: MAX_EDGE, h: 900 }]);
});

test("a frame already within the limit is not upscaled", async () => {
  const stopped = [];
  stubBrowser({
    getDisplayMedia: async () => aStream(stopped),
    videoSize: { width: 1280, height: 720 },
  });
  const shot = await captureScreenshot();
  assert.deepEqual([shot.width, shot.height], [1280, 720]);
});

test("every track is stopped, so the sharing indicator does not stay on", async () => {
  const stopped = [];
  stubBrowser({ getDisplayMedia: async () => aStream(stopped) });
  await captureScreenshot();
  assert.deepEqual(stopped, ["a", "b"]);
});

test("tracks are stopped even when the capture fails", async () => {
  const stopped = [];
  stubBrowser({
    getDisplayMedia: async () => aStream(stopped),
    videoSize: { width: 0, height: 0 },
  });
  await assert.rejects(() => captureScreenshot());
  assert.deepEqual(stopped, ["a", "b"]);
});

test("the encoder's own answer decides the content type, not the request", async () => {
  const stopped = [];
  stubBrowser({ getDisplayMedia: async () => aStream(stopped) });
  // The stub echoes the requested type, so WebP is what comes back.
  assert.equal((await captureScreenshot()).contentType, "image/webp");
});
