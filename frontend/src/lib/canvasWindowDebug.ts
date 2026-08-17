import type { CanvasWindowSnapshot } from "./canvasHistory.ts";
import { describeFold } from "./canvasHistory.ts";

export type CanvasCompactDebugEvent = {
  type: "compact";
  trigger: "forced" | "opportunistic" | "remote";
  foldedCount: number;
  pngBytes: number;
  elapsedMs: number;
  before: CanvasWindowSnapshot;
  after: CanvasWindowSnapshot;
};

export type CanvasWindowDebugEvent =
  | { type: "window"; snapshot: CanvasWindowSnapshot; semantic: boolean }
  | CanvasCompactDebugEvent;

function percent(value: number, max: number): number {
  return max > 0 ? Math.round((100 * value) / max) : 0;
}

function meter(percentValue: number): string {
  const filled = Math.min(10, Math.max(0, Math.round(percentValue / 10)));
  return `${"█".repeat(filled)}${"░".repeat(10 - filled)}`;
}

export function formatByteSize(bytes: number): string {
  if (bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes}B`;
  return `${(bytes / 1024).toFixed(1)}KiB`;
}

export function formatWindowLog(snapshot: CanvasWindowSnapshot): string {
  const workPct = percent(snapshot.work, snapshot.maxWork);
  const actionPct = percent(snapshot.actionCount, snapshot.maxActions);
  const pointPct = percent(snapshot.points, snapshot.maxPoints);
  const hottest = (
    [
      ["work", workPct],
      ["actions", actionPct],
      ["points", pointPct],
    ] as const
  ).reduce((best, candidate) => (candidate[1] > best[1] ? candidate : best));
  return (
    `work=${snapshot.work}/${snapshot.maxWork} (${workPct}%) `
    + `actions=${snapshot.actionCount}/${snapshot.maxActions} (${actionPct}%) `
    + `points=${snapshot.points}/${snapshot.maxPoints} (${pointPct}%) `
    + `png=${snapshot.pngBytes}B hottest=${hottest[0]}@${hottest[1]}% `
    + `compact80=${describeFold(snapshot.opportunisticFold)} `
    + `next_fill=${describeFold(snapshot.nextFillFold)} `
    + `next_stroke=${describeFold(snapshot.nextStrokeFold)}`
  );
}

export function formatCompactLog(event: CanvasCompactDebugEvent): string {
  const timing = event.elapsedMs > 0 ? ` ${event.elapsedMs}ms` : "";
  return (
    `${event.trigger} folded=${event.foldedCount} png=${formatByteSize(event.pngBytes)}`
    + `${timing} work ${percent(event.before.work, event.before.maxWork)}%`
    + ` → ${percent(event.after.work, event.after.maxWork)}%`
  );
}

export function formatCompactOverlay(event: CanvasCompactDebugEvent): string {
  const timing = event.elapsedMs > 0 ? `  ${event.elapsedMs}ms` : "";
  return (
    `${event.trigger} ×${event.foldedCount}${timing}  ${formatByteSize(event.pngBytes)}\n`
    + `     work ${percent(event.before.work, event.before.maxWork)}%`
    + ` → ${percent(event.after.work, event.after.maxWork)}%`
  );
}

export function formatWindowOverlay(
  snapshot: CanvasWindowSnapshot,
  lastCompact: string,
): string {
  const workPct = percent(snapshot.work, snapshot.maxWork);
  const actionPct = percent(snapshot.actionCount, snapshot.maxActions);
  const pointPct = percent(snapshot.points, snapshot.maxPoints);
  const lines = [
    `work ${String(workPct).padStart(3)}%  ${snapshot.work}/${snapshot.maxWork}  ${meter(workPct)}`,
    `act  ${String(actionPct).padStart(3)}%  ${snapshot.actionCount}/${snapshot.maxActions}  ${meter(actionPct)}`,
    `pts  ${String(pointPct).padStart(3)}%  ${snapshot.points}/${snapshot.maxPoints}  ${meter(pointPct)}`,
    `png  ${formatByteSize(snapshot.pngBytes)}`,
    `next fill ${describeFold(snapshot.nextFillFold)} · stroke ${describeFold(snapshot.nextStrokeFold)}`,
  ];
  if (lastCompact) lines.push(`last ${lastCompact}`);
  return lines.join("\n");
}
