import type { PromptLanguage } from "../types";
import { PROMPT_LANGUAGE_LABELS, SUPPORTED_PROMPT_LANGUAGES } from "./promptLanguages.ts";

/**
 * The languages a player plays in (#1208): a default, and the others in the
 * order the player ranked them. The default seats them in a mixed room and is
 * where Quick play opens a room; the others widen the lobby after mixed rooms.
 *
 * Pure, so the rules the server also holds - never the default among the
 * others, never one twice, at most every other language - are tested without
 * a store (`tests/playLanguages.test.mjs`).
 */
export const MAX_EXTRA_PROMPT_LANGUAGES = SUPPORTED_PROMPT_LANGUAGES.length - 1;

function isPromptLanguage(value: unknown): value is PromptLanguage {
  return typeof value === "string" && value in PROMPT_LANGUAGE_LABELS;
}

/** The others as the rules allow them: known languages, each once, never the
default, in the order given. Anything else in `value` is dropped rather than
refused, since it comes from storage or an older copy, not from a choice. */
export function normalizeExtraPromptLanguages(
  value: unknown,
  defaultLanguage: PromptLanguage,
): PromptLanguage[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<PromptLanguage>([defaultLanguage]);
  const extras: PromptLanguage[] = [];
  for (const language of value) {
    if (!isPromptLanguage(language) || seen.has(language)) continue;
    seen.add(language);
    extras.push(language);
  }
  return extras.slice(0, MAX_EXTRA_PROMPT_LANGUAGES);
}

export interface PlayLanguages {
  promptLanguage: PromptLanguage;
  extraPromptLanguages: PromptLanguage[];
}

/** A new default. One of the others is swapped with the old default, so
choosing a language never loses one; any other replaces it - the server's
rule too (#1209). */
export function chooseDefaultPlayLanguage(
  current: PlayLanguages,
  next: PromptLanguage,
): PlayLanguages {
  if (next === current.promptLanguage) return current;
  const at = current.extraPromptLanguages.indexOf(next);
  if (at < 0) return { ...current, promptLanguage: next };
  const extras = [...current.extraPromptLanguages];
  extras[at] = current.promptLanguage;
  return { promptLanguage: next, extraPromptLanguages: extras };
}

export function addExtraPromptLanguage(
  current: PlayLanguages,
  language: PromptLanguage,
): PlayLanguages {
  return {
    ...current,
    extraPromptLanguages: normalizeExtraPromptLanguages(
      [...current.extraPromptLanguages, language],
      current.promptLanguage,
    ),
  };
}

export function removeExtraPromptLanguage(
  current: PlayLanguages,
  language: PromptLanguage,
): PlayLanguages {
  return {
    ...current,
    extraPromptLanguages: current.extraPromptLanguages.filter((item) => item !== language),
  };
}

/** `extras` with the one at `from` moved to `to`, both clamped to the list. */
export function moveExtraPromptLanguage(
  extras: readonly PromptLanguage[],
  from: number,
  to: number,
): PromptLanguage[] {
  const last = extras.length - 1;
  if (from < 0 || from > last) return [...extras];
  const target = Math.max(0, Math.min(last, to));
  const moved = [...extras];
  const [language] = moved.splice(from, 1);
  moved.splice(target, 0, language);
  return moved;
}

/** Languages the browser says this person reads, that they do not play in yet
and have not waved away: offered, never added for them - a browser lists
English as a fallback for plenty of people who could not play a round in it. */
export function suggestedExtraPromptLanguages(
  browserLanguages: readonly string[] | undefined,
  current: PlayLanguages,
  dismissed: readonly string[] = [],
): PromptLanguage[] {
  const taken = new Set<string>([
    current.promptLanguage,
    ...current.extraPromptLanguages,
    ...dismissed,
  ]);
  const suggested: PromptLanguage[] = [];
  for (const tag of browserLanguages ?? []) {
    const base = tag.trim().toLowerCase().split("-", 1)[0];
    if (!isPromptLanguage(base) || taken.has(base)) continue;
    taken.add(base);
    suggested.push(base);
  }
  return suggested.slice(
    0,
    Math.max(0, MAX_EXTRA_PROMPT_LANGUAGES - current.extraPromptLanguages.length),
  );
}
