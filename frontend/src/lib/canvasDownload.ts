import { CANVAS_HEIGHT, CANVAS_WIDTH } from "./canvasHistory.ts";
import { encodePng } from "./pngEncode.ts";

export function getCanvasDownloadName(downloadPrompt: string | null): string {
  const date = new Date();
  const datePart = [
    String(date.getFullYear()).slice(-2),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
    String(date.getHours()).padStart(2, "0"),
    String(date.getMinutes()).padStart(2, "0"),
  ].join("");
  const prompt = downloadPrompt
    ? downloadPrompt.trim().toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9_-]/g, "")
    : "";
  return `sketchy-${datePart}${prompt ? `-${prompt}` : ""}.png`;
}

/** Save the drawing as a PNG made from its own pixels (`pngEncode.ts`), never
from a canvas read, which a privacy protection may answer with noise. */
export async function saveCanvasImage(
  pixels: Uint8ClampedArray | null,
  downloadPrompt: string | null,
): Promise<void> {
  if (!pixels) return;
  const png = await encodePng(pixels, CANVAS_WIDTH, CANVAS_HEIGHT);
  const url = URL.createObjectURL(new Blob([png as BlobPart], { type: "image/png" }));
  const link = document.createElement("a");
  link.download = getCanvasDownloadName(downloadPrompt);
  link.href = url;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // Not at once: a browser may still be reading the URL when click() returns.
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
