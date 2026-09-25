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

/**
 * Is there nothing in this slice to show but names?
 *
 * Then the table has nothing to say: every row would read "Not played
 * enough", a dash, a dash and a zero, forty to a page. The page says why
 * once (`coverageNote`) and lists the prompts as names instead (R-STAT-02).
 * Only while nothing has been drawn either: a prompt drawn a few times has a
 * count worth showing and an order ("Most picked") worth keeping, ranked or
 * not, and the table keeps both.
 */
export function nothingRanked(stats: {
  ratedCount: number;
  unratedCount: number;
  prompts: readonly Pick<PromptStats, "pickCount">[];
}): boolean {
  return stats.ratedCount === 0
    && stats.unratedCount > 0
    && stats.prompts.every((prompt) => prompt.pickCount === 0);
}

/** The names of an unranked list, alphabetically in the list's own language:
    with no difficulty to order them by, the order a reader can scan is the
    only useful one. */
export function plainPromptNames(prompts: PromptStats[], language: string): string[] {
  const collator = new Intl.Collator(language, { sensitivity: "base" });
  return prompts.map((prompt) => prompt.text).sort(collator.compare);
}

/**
 * A prompt from the list itself, as the search box's example.
 *
 * A fixed English example sat in the box above a German list. The middle name
 * alphabetically is stable across sorts and filters, which all list the same
 * prompts, so the example does not change under the reader's cursor.
 */
export function searchExample(prompts: PromptStats[], language: string): string | null {
  if (prompts.length === 0) return null;
  const names = plainPromptNames(prompts, language);
  return names[Math.floor(names.length / 2)];
}
