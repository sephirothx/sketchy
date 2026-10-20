/**
 * Solo's play in the browser (#1434): the clock, where it started, and how a
 * Daily's drawings read as marks. Pure apart from the clock's memory, so the
 * node suite can hold it to its edges.
 */
import { localDateKey, type SoloDailyResult } from "./solo.ts";

/** The clock a drawing is guessed against, and the part its strokes take. */
export const SOLO_CLOCK_SECONDS = 30;
export const SOLO_REPLAY_SECONDS = 20;

const STARTED_PREFIX = "sketchy_solo_started_";

/**
 * When this drawing was first shown, remembered in the browser: a reload
 * continues its clock rather than starting it again. Lost storage (a private
 * window, a cleared site) starts it again - the server bounds what any clock
 * can report. `drawing` tells the drawing behind the serve apart: a Daily
 * replaced for everybody keeps its serve id and changes what it holds, and
 * a new drawing gets a new clock.
 */
export function serveStartedAt(serveId: string, drawing: string, now: number = Date.now()): number {
  const tag = fingerprint(drawing);
  try {
    const [at, kept] = (localStorage.getItem(STARTED_PREFIX + serveId) ?? "").split("|");
    const started = Number(at);
    if (kept === tag && Number.isFinite(started) && started > 0 && started <= now) return started;
    localStorage.setItem(STARTED_PREFIX + serveId, `${now}|${tag}`);
  } catch {
    // Storage refused: this showing's own clock.
  }
  return now;
}

/** A short stable tag for a string: enough to tell two drawings apart. */
export function fingerprint(text: string): string {
  let hash = 5381;
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash * 33) ^ text.charCodeAt(index)) >>> 0;
  }
  return hash.toString(36);
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

export type StreakTier = "start" | "week" | "month" | "year";

/** Where a streak stands between its milestones - a week, a month (30 days)
    and a year, then every year after: the one it passed (`from`, 0 before the
    first), the one it runs to (`goal`), and whether today is a milestone. */
export function streakMilestone(days: number): {
  tier: StreakTier;
  from: number;
  goal: number;
  reached: boolean;
  fraction: number;
} {
  const from = days >= 365 ? Math.floor(days / 365) * 365 : days >= 30 ? 30 : days >= 7 ? 7 : 0;
  const goal = days >= 365 ? from + 365 : days >= 30 ? 365 : days >= 7 ? 30 : 7;
  const tier: StreakTier = days >= 365 ? "year" : days >= 30 ? "month" : days >= 7 ? "week" : "start";
  const reached = from > 0 && days === from;
  return { tier, from, goal, reached, fraction: reached ? 1 : (days - from) / (goal - from) };
}

/** Milliseconds until the player's own midnight, when the next Daily opens. */
export function untilLocalMidnight(now: Date = new Date()): number {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 0, 0);
  return midnight.getTime() - now.getTime();
}

/** How often a page open on Solo looks at the date, besides waking up. */
export const LOCAL_DATE_CHECK_MS = 30_000;

/**
 * Call `onChange` with the player's new local date when it changes: the
 * Daily rolls over at their midnight, and a page left open across it - or a
 * tab woken after it - must ask for the new one (R-SOLO-12, #1495 review).
 * Looked at every half minute and whenever the tab is shown or focused.
 * Returns the way to stop.
 */
export function watchLocalDate(
  onChange: (date: string) => void,
  read: () => string = () => localDateKey(),
): () => void {
  let current = read();
  const check = () => {
    const now = read();
    if (now === current) return;
    current = now;
    onChange(now);
  };
  const timer = setInterval(check, LOCAL_DATE_CHECK_MS);
  document.addEventListener("visibilitychange", check);
  window.addEventListener("focus", check);
  return () => {
    clearInterval(timer);
    document.removeEventListener("visibilitychange", check);
    window.removeEventListener("focus", check);
  };
}
