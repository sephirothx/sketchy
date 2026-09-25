/** Which of a profile's statistics are drawn, and which say nothing yet.

A brand-new player was shown nine zeros and a "0% win rate": tiles describing
nothing, laid out as though they did. The rule is not "hide at zero games",
though. A game that was abandoned still counts the turns that were drawn and
guessed in it - the drawings were made, and reacted to - but not a game played,
a win, or a score (`services/user_stats_projection.py`). So a player whose only
games fell apart has real turn counts and zeros for everything a finished game
decides, and hiding every tile would hide the numbers that are true.

With no finished game, then, the game tiles give way to one line and only the
turn counts that are not zero stay. Kept free of runtime imports so the node
test runner can load it. */
import type { ProfileStats } from "./profile";

/** Counted per turn, so an abandoned game adds to them. */
export const TURN_STATS = [
  "turnsPlayed",
  "promptsGuessed",
  "drawingsMade",
  "reactionsReceived",
] as const;

export type TurnStat = (typeof TURN_STATS)[number];

export interface StatisticsLayout {
  /** Games played, won, win rate, average and total score: finished games only. */
  gameStats: boolean;
  /** The per-turn counts to draw, in their usual order. */
  turnStats: readonly TurnStat[];
}

export function statisticsLayout(
  stats: Pick<ProfileStats, "gamesPlayed" | TurnStat>,
): StatisticsLayout {
  if (stats.gamesPlayed > 0) return { gameStats: true, turnStats: TURN_STATS };
  return {
    gameStats: false,
    turnStats: TURN_STATS.filter((key) => stats[key] > 0),
  };
}
