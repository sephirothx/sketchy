import { emitWithAck } from "./socket";
import type { ReactToDrawingResponse } from "../types";
import { refusalText } from "./refusals.ts";
import { ui } from "../content/ui/index.ts";

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
    throw new Error(refusalText(response, ui.reactionRequests.thatReactionCouldNotBeSent));
  }
  return response;
}
