/**
 * Solo's play in the browser (#1434): the clock, where it started, and how a
 * Daily's drawings read as marks. Pure apart from the clock's memory, so the
 * node suite can hold it to its edges.
 */
import type { SoloDailyResult } from "./solo";

/** The clock a drawing is guessed against, and the part its strokes take. */
export const SOLO_CLOCK_SECONDS = 30;
export const SOLO_REPLAY_SECONDS = 20;

const STARTED_PREFIX = "sketchy_solo_started_";

/**
 * When this drawing was first shown, remembered in the browser: a reload
 * continues its clock rather than starting it again. Lost storage (a private
 * window, a cleared site) starts it again - the server bounds what any clock
 * can report.
 */
export function serveStartedAt(serveId: string, now: number = Date.now()): number {
  try {
    const kept = Number(localStorage.getItem(STARTED_PREFIX + serveId));
    if (Number.isFinite(kept) && kept > 0 && kept <= now) return kept;
    localStorage.setItem(STARTED_PREFIX + serveId, String(now));
  } catch {
    // Storage refused: this showing's own clock.
  }
  return now;
}

export function forgetServeStart(serveId: string): void {
  try {
    localStorage.removeItem(STARTED_PREFIX + serveId);
  } catch {
    // Nothing kept, nothing to forget.
  }
}

export type DailyMark = "solved" | "missed" | "unplayed";

/** A Daily's five positions, in order: named, missed, or still to play. */
export function dailyMarks(result: SoloDailyResult): DailyMark[] {
  const marks: DailyMark[] = result.marks.map((mark) => (mark.outcome === "solved" ? "solved" : "missed"));
  while (marks.length < 5) marks.push("unplayed");
  return marks.slice(0, 5);
}

/** Milliseconds until the player's own midnight, when the next Daily opens. */
export function untilLocalMidnight(now: Date = new Date()): number {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 0, 0);
  return midnight.getTime() - now.getTime();
}
