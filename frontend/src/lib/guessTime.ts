/**
 * How long into the drawing a correct guess landed, as every surface shows it:
 * the chat's got-it line, the players panel, and the results card. The seconds
 * are always the server's (`correct_guess`, `sync_game`, `turn_ended`), so the
 * same guess reads the same everywhere (R-CONN-13) — each client used to time
 * the chat line and the panel on its own clock, in whole seconds, while the
 * results card showed the server's tenths.
 *
 * Tenths under a minute ("3.6s"), minutes and tenths from there ("1:04.3").
 * Rounded once up front, so 59.96 reads "1:00.0" rather than "60.0s".
 */
export function formatGuessTime(seconds: number): string {
  const tenths = Math.max(0, Math.round(seconds * 10));
  if (tenths < 600) return `${(tenths / 10).toFixed(1)}s`;
  const minutes = Math.floor(tenths / 600);
  return `${minutes}:${((tenths % 600) / 10).toFixed(1).padStart(4, "0")}`;
}
