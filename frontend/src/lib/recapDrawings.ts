import { emitWithAck } from "./socket";
import type { DrawingRecapMetadata, DrawingRecapResponse } from "../types";

/**
 * Fetch a drawing the live room still holds in memory.
 *
 * The room answers over the socket by index, because a recap is a position in
 * a list the room just sent. A finished game answers over HTTP by turn id
 * instead; both hand back the same wire format, which is what lets one gallery
 * render either.
 */
export async function loadRecapDrawing(
  entry: DrawingRecapMetadata,
): Promise<unknown> {
  const response = await emitWithAck<DrawingRecapResponse>("get_recap_drawing", {
    index: entry.index,
  });
  if (!response.ok || !response.drawing) {
    throw new Error(response.error || "This drawing could not be loaded.");
  }
  return response.drawing.canvas;
}
