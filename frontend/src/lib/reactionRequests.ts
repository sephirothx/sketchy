import { emitWithAck } from "./socket";
import type { ReactToDrawingResponse } from "../types";

/**
 * React to a drawing the live room is showing - the current turn's, or one in
 * the recap. `emoji: null` takes the reaction back. Acknowledged rather than
 * fire-and-forget: a control somebody pressed has to be able to say why it
 * did nothing.
 */
export async function sendDrawingReaction(
  turnId: string,
  emoji: string | null,
): Promise<ReactToDrawingResponse> {
  const response = await emitWithAck<ReactToDrawingResponse>("react_to_drawing", {
    turnId,
    emoji,
  });
  if (!response.ok) {
    throw new Error(response.error || "That reaction could not be sent.");
  }
  return response;
}
