import type { PromptStats, PromptStatsSort } from "../types";

export const PROMPT_STATS_SORTS: { value: PromptStatsSort; label: string }[] = [
  { value: "hardest", label: "Hardest first" },
  { value: "easiest", label: "Easiest first" },
  { value: "most-picked", label: "Most picked" },
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
  if (ratio >= 0.85) return "Gets guessed";
  if (ratio >= 0.6) return "Usually guessed";
  if (ratio >= 0.35) return "Even odds";
  if (ratio >= 0.15) return "Often missed";
  return "Rarely guessed";
}

/** What the table is showing, and what it is still waiting on. */
export function coverageNote(
  ratedCount: number,
  unratedCount: number,
  minRatedGuessers: number,
): string | null {
  if (ratedCount === 0 && unratedCount === 0) return null;
  if (unratedCount === 0) {
    return `All ${ratedCount} prompts have been played enough to rank.`;
  }
  if (ratedCount === 0) {
    return (
      `None of these ${unratedCount} prompts has faced ${minRatedGuessers} guessers `
      + "yet, so none of them is ranked. Play some games and their difficulty will "
      + "show up here."
    );
  }
  const prompts = unratedCount === 1 ? "prompt is" : "prompts are";
  return (
    `${ratedCount} ranked. ${unratedCount} more ${prompts} unranked: fewer than `
    + `${minRatedGuessers} guessers have seen them.`
  );
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
  if (matches === 0) return `No prompt matches “${query.trim()}”.`;
  return `${matches} prompt${matches === 1 ? "" : "s"} matching “${query.trim()}”.`;
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
    band: prompt.isRated ? difficultyBand(prompt.correctGuessRatio) : "Not played enough",
    pickedLabel: prompt.isRated ? ratioLabel(prompt.pickRate) : "—",
    drawnLabel: String(prompt.pickCount),
  }));
}
