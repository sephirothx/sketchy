import { emitWithAck } from "./socket";
import type { ShareDrawingResponse } from "../types";

/**
 * Share a drawing the live room is showing to the Gallery - the finished
 * turn's results, or one in the recap - or take the share back (#1430).
 * Acknowledged, so a press can say why it did nothing; a refusal is thrown as
 * it came, code and all, for the control to word.
 */
export async function sendDrawingShare(
  turnId: string,
  shared: boolean,
): Promise<ShareDrawingResponse> {
  const response = await emitWithAck<ShareDrawingResponse>("share_drawing", { turnId, shared });
  if (!response.ok) throw response;
  return response;
}
