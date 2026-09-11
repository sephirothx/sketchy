import type { PromptStats, PromptStatsSort } from "../types";
import { ui } from "../content/ui/index.ts";

export const PROMPT_STATS_SORTS: { value: PromptStatsSort; label: string }[] = [
  { value: "hardest", get label() { return ui.promptStats.hardestFirst; } },
  { value: "easiest", get label() { return ui.promptStats.easiestFirst; } },
  { value: "most-picked", get label() { return ui.promptStats.mostPicked; } },
];

export function isPromptStatsSort(value: string): value is PromptStatsSort {
  return PROMPT_STATS_SORTS.some((sort) => sort.value === value);
}

/** A ratio as a whole percentage. */
export function ratioLabel(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

/**
 * How the prompt went, in words.
 *
 * The percentage alone reads as precision the sample does not have - a prompt
 * six guessers have seen is not measured to the point - so the table leads with
 * a band and keeps the number beside it.
 */
export function difficultyBand(ratio: number): string {
  if (ratio >= 0.85) return ui.promptStats.getsGuessed;
  if (ratio >= 0.6) return ui.promptStats.usuallyGuessed;
  if (ratio >= 0.35) return ui.promptStats.evenOdds;
  if (ratio >= 0.15) return ui.promptStats.oftenMissed;
  return ui.promptStats.rarelyGuessed;
}

/** What the table is showing, and what it is still waiting on. */
export function coverageNote(
  ratedCount: number,
  unratedCount: number,
  minRatedGuessers: number,
): string | null {
  if (ratedCount === 0 && unratedCount === 0) return null;
  if (unratedCount === 0) {
    return ui.promptStats.allRanked({ count: ratedCount });
  }
  if (ratedCount === 0) {
    return ui.promptStats.noneRanked({ unrated: unratedCount, guessers: minRatedGuessers });
  }
  return ui.promptStats.someRanked({
    rated: ratedCount,
    unrated: unratedCount,
    guessers: minRatedGuessers,
  });
}

/** Prompts whose text contains the query, case- and space-insensitively. */
export function matchingPrompts(
  prompts: PromptStats[],
  query: string,
): PromptStats[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return prompts;
  return prompts.filter((prompt) => prompt.text.toLowerCase().includes(needle));
}

export function searchNote(query: string, matches: number): string | null {
  if (!query.trim()) return null;
  if (matches === 0) return ui.promptStats.noMatch({ query: query.trim() });
  return ui.promptStats.matching({ count: matches, query: query.trim() });
}

/**
 * The rows, already ordered by the server, with their display fields.
 *
 * An unrated prompt gets no band and no percentages: it has been offered too
 * little to have a difficulty, and printing "0%" beside it would read as one.
 * How many times it has been drawn is a plain count either way, and true of a
 * prompt drawn twice as much as one drawn fifty times.
 */
export function statsRows(prompts: PromptStats[]) {
  return prompts.map((prompt) => ({
    ...prompt,
    guessedLabel: prompt.isRated ? ratioLabel(prompt.correctGuessRatio) : "—",
    band: prompt.isRated ? difficultyBand(prompt.correctGuessRatio) : ui.promptStats.notPlayedEnough,
    pickedLabel: prompt.isRated ? ratioLabel(prompt.pickRate) : "—",
    drawnLabel: String(prompt.pickCount),
  }));
}
