import type { ServerPausedNotice, ServerShutdownNotice } from "../types";

/**
 * Accept only the shutdown contract this build understands. A later server may
 * widen the notice or announce a different reason, and a half-understood banner
 * telling players the wrong thing is worse than no banner at all.
 */
export function parseShutdownNotice(
  payload: unknown,
): ServerShutdownNotice | null {
  if (!payload || typeof payload !== "object") return null;
  const notice = payload as Partial<ServerShutdownNotice>;
  if (notice.contractVersion !== 1 || notice.reason !== "deployment") return null;
  if (typeof notice.startedAt !== "string") return null;
  if (
    typeof notice.drainSeconds !== "number" ||
    !Number.isFinite(notice.drainSeconds) ||
    notice.drainSeconds < 0
  ) {
    return null;
  }
  return {
    contractVersion: 1,
    reason: "deployment",
    drainSeconds: notice.drainSeconds,
    startedAt: notice.startedAt,
  };
}

/**
 * Seconds left in the drain window, from the moment the server started it.
 *
 * Clamped to the window the server announced: the deadline is the server's,
 * measured against a clock this browser does not share, and a skewed one must
 * not be able to promise more time than was ever offered - or count into
 * negatives after the window has closed.
 *
 * The announced window is the exact one the server will wait, fractions and
 * all, because that is what the contract is for. Turning it into whole seconds
 * is a display decision and belongs here, and it rounds *up*, as a countdown
 * does: a 1.25-second window reads 2, then 1, then 0.
 *
 * So the number on screen can be up to a second larger than what is literally
 * left. What it cannot do is outlast the deadline - `ceil` reaches 0 exactly
 * when the window closes, never after - and the clamp keeps a skewed clock
 * from showing more than the announced window in the first place. Those two
 * are the guarantees; "never more than the time remaining" is not one of them,
 * and rounding down to get it would show 0 while the server was still waiting.
 */
export function shutdownSecondsRemaining(
  notice: ServerShutdownNotice,
  now: number = Date.now(),
): number {
  const startedAt = Date.parse(notice.startedAt);
  if (Number.isNaN(startedAt)) return notice.drainSeconds;
  const remaining = (startedAt + notice.drainSeconds * 1000 - now) / 1000;
  return Math.min(Math.ceil(notice.drainSeconds), Math.max(0, Math.ceil(remaining)));
}

/**
 * Accept only the pause contract this build understands.
 *
 * Separate from the shutdown notice above, and deliberately so: a pause says
 * this server is still here and will take the room shortly, where a drain says
 * it is going away and a reload will find another. Telling a player the wrong
 * one of those sends them off to reload a page that was about to work.
 */
export function parsePausedNotice(payload: unknown): ServerPausedNotice | null {
  if (!payload || typeof payload !== "object") return null;
  const notice = payload as Partial<ServerPausedNotice>;
  if (notice.contractVersion !== 1 || notice.reason !== "maintenance") return null;
  if (typeof notice.paused !== "boolean") return null;
  return { contractVersion: 1, paused: notice.paused, reason: "maintenance" };
}
