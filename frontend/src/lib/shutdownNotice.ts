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
