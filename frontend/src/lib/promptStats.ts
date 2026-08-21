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

/**
 * What to say instead of a table.
 *
 * A brand-new server has recorded nothing, which is not the same as a list
 * whose prompts have all been played but none often enough to rank. Saying
 * "no results" to both would hide the difference.
 */
export function emptyStatsMessage(
  ratedCount: number,
  unratedCount: number,
  minRatedGuessers: number,
): string | null {
  if (ratedCount > 0) return null;
  if (unratedCount === 0) return "This prompt list has no prompts yet.";
  return (
    `None of these ${unratedCount} prompts has faced ${minRatedGuessers} guessers yet. `
    + "Play some games and their difficulty will show up here."
  );
}

export function unratedNote(
  unratedCount: number,
  minRatedGuessers: number,
): string | null {
  if (unratedCount === 0) return null;
  const prompts = unratedCount === 1 ? "prompt is" : "prompts are";
  return (
    `${unratedCount} more ${prompts} not ranked yet: fewer than `
    + `${minRatedGuessers} guessers have seen them.`
  );
}

/** The rows, already ordered by the server, with their display fields. */
export function statsRows(prompts: PromptStats[]) {
  return prompts.map((prompt) => ({
    ...prompt,
    guessedLabel: ratioLabel(prompt.correctGuessRatio),
    band: difficultyBand(prompt.correctGuessRatio),
    pickedLabel: ratioLabel(prompt.pickRate),
  }));
}
