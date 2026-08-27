/** One frame of the player's screen, for a bug report that needs a picture.

`getDisplayMedia` rather than rasterizing the DOM: the game is a canvas, and a
library that re-implements CSS gets canvas-heavy screens wrong in exactly the
cases somebody is trying to report. It also means the browser's own picker is
the consent step - the player chooses what to share, in an interface we cannot
dress up - and there is no dependency to carry.

The cost is that it is desktop-only. `canCaptureScreen` exists so the dialog can
leave the button out rather than offer one that throws, and the description
stands alone on a phone. */

/** The long edge a screenshot is scaled down to. Large enough to read a
    timer and a chat line, small enough to stay well inside the 2 MB cap. */
export const MAX_EDGE = 1600;
export const MAX_BYTES = 2 * 1024 * 1024;

/** How long to wait for the concealed page to reach the capture stream. */
const CONCEAL_SETTLE_MS = 700;
/** Frames to let pass after concealing. A display stream is composited
    asynchronously, so the first frame after a style change is often still the
    old picture. */
const CONCEAL_SETTLE_FRAMES = 3;

export interface CapturedScreenshot {
  /** Base64 with no data: prefix - the wire carries bytes, not a URL. */
  base64: string;
  contentType: "image/webp" | "image/png";
  width: number;
  height: number;
  byteSize: number;
  /** For the preview the player has to look at before sending. */
  previewUrl: string;
}

type DisplayMediaCapable = MediaDevices & {
  getDisplayMedia?: (constraints?: unknown) => Promise<MediaStream>;
};

export function canCaptureScreen(): boolean {
  return typeof navigator?.mediaDevices !== "undefined"
    && typeof (navigator.mediaDevices as DisplayMediaCapable).getDisplayMedia === "function";
}

function scaled(width: number, height: number): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= MAX_EDGE) return { width, height };
  const factor = MAX_EDGE / longest;
  return {
    width: Math.max(1, Math.round(width * factor)),
    height: Math.max(1, Math.round(height * factor)),
  };
}

async function encode(canvas: HTMLCanvasElement): Promise<{ blob: Blob; contentType: "image/webp" | "image/png" }> {
  const webp = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/webp", 0.8),
  );
  // A browser that cannot encode WebP hands back a PNG under the name it was
  // asked for, so the blob's own type is what decides - not the request.
  if (webp && webp.type === "image/webp") return { blob: webp, contentType: "image/webp" };
  const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!png) throw new Error("This browser could not encode the screenshot.");
  return { blob: png, contentType: "image/png" };
}

type FrameCapableVideo = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: () => void) => number;
};

/** Wait until the stream has delivered frames drawn after the last change.
 *
 * `requestVideoFrameCallback` is the precise tool - it fires when a new frame
 * is ready for display - but a screen stream that thinks nothing is happening
 * can go quiet, so every wait is bounded and the deadline is shared. Timing out
 * is not an error: it means taking the picture slightly sooner than ideal,
 * which beats hanging on a browser that never fires.
 */
async function settleFrames(video: HTMLVideoElement): Promise<void> {
  const deadline = Date.now() + CONCEAL_SETTLE_MS;
  const frameCallback = (video as FrameCapableVideo).requestVideoFrameCallback;
  for (let taken = 0; taken < CONCEAL_SETTLE_FRAMES; taken += 1) {
    const remaining = deadline - Date.now();
    if (remaining <= 0) return;
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(finish, remaining);
      if (typeof frameCallback === "function") frameCallback.call(video, finish);
      else requestAnimationFrame(finish);
    });
  }
}

/** Hide `element` without disturbing the layout behind it.
 *
 * `visibility` rather than `display`: taking the element out of flow can move
 * the page underneath - a scrollbar appearing is enough - and the whole point
 * is to photograph that page exactly as it stands.
 */
function conceal(element: HTMLElement): () => void {
  const previous = element.style.visibility;
  element.style.visibility = "hidden";
  return () => {
    element.style.visibility = previous;
  };
}

async function toBase64(blob: Blob): Promise<string> {
  const buffer = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  // Chunked: spreading a megabyte into String.fromCharCode blows the argument
  // limit on exactly the large screenshots this is for.
  for (let index = 0; index < buffer.length; index += 8192) {
    binary += String.fromCharCode(...buffer.subarray(index, index + 8192));
  }
  return btoa(binary);
}

/** Ask for one frame. Resolves to null when the player cancels the picker.
 *
 * Cancelling is an answer, not a failure: it rejects with `NotAllowedError`,
 * and treating that as an error would put a red message in front of somebody
 * who simply changed their mind.
 *
 * `hide` is the element to take out of the picture first - in practice the
 * report dialog itself, which is otherwise the only thing in the shot. A
 * screenshot of the form asking for a screenshot is worth nothing; what triage
 * needs is the page behind it. The element is restored however this ends.
 */
export async function captureScreenshot(
  { hide }: { hide?: HTMLElement | null } = {},
): Promise<CapturedScreenshot | null> {
  if (!canCaptureScreen()) return null;
  let stream: MediaStream | null = null;
  let restore: (() => void) | null = null;
  try {
    stream = await (navigator.mediaDevices as DisplayMediaCapable).getDisplayMedia!({
      // Bias the picker towards this tab, which is what the report is about.
      // Both hints are ignored where unsupported, which costs nothing.
      video: { displaySurface: "browser" },
      preferCurrentTab: true,
      audio: false,
    });

    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    // One frame has to have arrived before the canvas is drawn from it;
    // `play()` resolves before that on some browsers.
    await new Promise((resolve) => requestAnimationFrame(resolve));

    // Hide first, then wait for the stream to actually show the page without
    // it. Restored in this function's `finally`, so a throw between here and
    // the draw cannot leave the dialog invisible.
    restore = hide ? conceal(hide) : null;
    if (restore) await settleFrames(video);

    const source = { width: video.videoWidth, height: video.videoHeight };
    if (!source.width || !source.height) throw new Error("The capture was empty.");
    const size = scaled(source.width, source.height);

    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("This browser could not read the screenshot.");
    context.drawImage(video, 0, 0, size.width, size.height);
    video.pause();
    video.srcObject = null;

    const { blob, contentType } = await encode(canvas);
    if (blob.size > MAX_BYTES) throw new Error("That screenshot is too large to send.");

    return {
      base64: await toBase64(blob),
      contentType,
      width: size.width,
      height: size.height,
      byteSize: blob.size,
      previewUrl: URL.createObjectURL(blob),
    };
  } catch (error) {
    if (error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "AbortError")) {
      return null;
    }
    throw error;
  } finally {
    // Whatever happened, the dialog comes back before anything else.
    restore?.();
    // Every track, always. A live track leaves the browser's sharing indicator
    // on, which reads as "this page is still watching you" - and would be true.
    stream?.getTracks().forEach((track) => track.stop());
  }
}
