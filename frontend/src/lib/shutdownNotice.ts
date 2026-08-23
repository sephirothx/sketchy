import type { ServerShutdownNotice } from "../types";

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
 */
export function shutdownSecondsRemaining(
  notice: ServerShutdownNotice,
  now: number = Date.now(),
): number {
  const startedAt = Date.parse(notice.startedAt);
  if (Number.isNaN(startedAt)) return notice.drainSeconds;
  const remaining = (startedAt + notice.drainSeconds * 1000 - now) / 1000;
  return Math.min(notice.drainSeconds, Math.max(0, Math.ceil(remaining)));
}
