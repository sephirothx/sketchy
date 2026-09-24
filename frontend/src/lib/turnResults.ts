import type { TurnEndedPayload } from "../types.ts";

/** Whether this `turn_ended` is one the results screen is already showing.

Every rebind that lands during a turn's results - a tab coming back, a
heartbeat that finds the phase moved, an ordinary reconnect - re-sends
`turn_ended` so the screen can be rebuilt, and each one appended another "The
prompt was …" line to the chat (#1018). Every turn has an id and the re-send
carries it, so that is what is compared. */
export function isTurnAlreadyShown(
  state: { phase: string; lastTurnResult: TurnEndedPayload | null },
  payload: TurnEndedPayload,
): boolean {
  const shown = state.lastTurnResult;
  if (state.phase !== "turn_results" || !shown || !payload.turnId) return false;
  return shown.turnId === payload.turnId;
}
