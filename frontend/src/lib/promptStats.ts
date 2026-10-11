import type { PromptListSummary, PromptStats, PromptStatsSort } from "../types";
import { promptLanguageLabel } from "./promptLanguages.ts";
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
    correctGuessRatio: correctGuessRatio(prompt),
    guessedLabel: prompt.isRated ? ratioLabel(correctGuessRatio(prompt)) : "—",
    band: prompt.isRated ? difficultyBand(correctGuessRatio(prompt)) : ui.promptStats.notPlayedEnough,
    pickedLabel: prompt.isRated ? ratioLabel(pickRate(prompt)) : "—",
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

/** How often a prompt was picked when offered (#1424): the server sends the
    counts and no longer the quotient, which cost half the response. */
export function pickRate(prompt: PromptStats): number {
  return prompt.offerCount > 0 ? prompt.pickCount / prompt.offerCount : 0;
}

/** The share of the guessers who faced a prompt that guessed it. */
export function correctGuessRatio(prompt: PromptStats): number {
  return prompt.totalGuesserCount > 0 ? prompt.correctGuessCount / prompt.totalGuesserCount : 0;
}

/** Code-point order, as the server sorts its text (Python's `<`). */
function byText(a: PromptStats, b: PromptStats): number {
  return a.text < b.text ? -1 : a.text > b.text ? 1 : 0;
}

/** The prompts in the order the server ranks them (`_ordered` in
    api/prompt_lists.py): rated ones by the sort, the rest alphabetically
    after them. Done here, so changing the sort is not another request for
    the same counts (#1424). */
export function sortPromptStats(prompts: readonly PromptStats[], sort: PromptStatsSort): PromptStats[] {
  const rated = prompts.filter((prompt) => prompt.isRated);
  const unrated = prompts.filter((prompt) => !prompt.isRated).sort(byText);
  const order: (a: PromptStats, b: PromptStats) => number =
    sort === "most-picked"
      ? (a, b) => pickRate(b) - pickRate(a) || b.pickCount - a.pickCount || byText(a, b)
      : sort === "easiest"
        ? (a, b) => correctGuessRatio(b) - correctGuessRatio(a) || byText(a, b)
        : (a, b) => correctGuessRatio(a) - correctGuessRatio(b) || byText(a, b);
  return [...rated.sort(order), ...unrated];
}

export interface ListLanguageGroup {
  language: string;
  label: string;
  lists: PromptListSummary[];
}

/** The lists grouped by language, the reader's play languages first in their
    order and the rest by name (#1424): 136 options in one column, thirty
    labels written twice - eight "League of Legends (173)" - was no way to
    find one. */
export function listsByLanguage(
  lists: readonly PromptListSummary[],
  playLanguages: readonly string[],
): ListLanguageGroup[] {
  const groups = new Map<string, PromptListSummary[]>();
  for (const list of lists) {
    const group = groups.get(list.language) ?? [];
    group.push(list);
    groups.set(list.language, group);
  }
  const rank = (language: string) => {
    const index = playLanguages.indexOf(language);
    return index === -1 ? playLanguages.length : index;
  };
  return [...groups.entries()]
    .map(([language, members]) => ({ language, label: promptLanguageLabel(language), lists: members }))
    .sort((a, b) => rank(a.language) - rank(b.language) || a.label.localeCompare(b.label));
}
