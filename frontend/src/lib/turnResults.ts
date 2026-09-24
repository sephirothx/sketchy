import type { TurnEndedPayload } from "../types.ts";

/** Whether this `turn_ended` is one the results screen is already showing.

Every rebind that lands during a turn's results - a tab coming back, a
heartbeat that finds the phase moved, an ordinary reconnect - re-sends
`turn_ended` so the screen can be rebuilt, and each one appended another "The
prompt was …" line to the chat (#1018). The state is simply re-applied; the
line is said once. A payload without a turn id (a server older than turn ids)
is matched on what it shows instead. */
export function isTurnAlreadyShown(
  state: { phase: string; lastTurnResult: TurnEndedPayload | null },
  payload: TurnEndedPayload,
): boolean {
  const shown = state.lastTurnResult;
  if (state.phase !== "turn_results" || !shown) return false;
  if (payload.turnId || shown.turnId) return shown.turnId === payload.turnId;
  return shown.prompt === payload.prompt && shown.drawerId === payload.drawerId;
}
