import type { PromptLanguage } from "../types";

export const PROMPT_LANGUAGE_LABELS: Record<PromptLanguage, string> = {
  de: "German",
  en: "English",
  es: "Spanish",
  fr: "French",
  it: "Italian",
  nl: "Dutch",
  pt: "Portuguese",
};

export function promptLanguageLabel(language: string): string {
  return PROMPT_LANGUAGE_LABELS[language as PromptLanguage] ?? language;
}

/**
 * The languages a host may open a room in, given the catalogue they can see.
 *
 * Only languages with content are offered: a room declares its language before
 * it picks lists, so a language with nothing to draw from would be a dead end
 * rather than a choice. `current` is always included, because a room that is
 * already in a language must still be able to describe itself while the
 * catalogue is loading or after a list is withdrawn.
 */
export function availablePromptLanguages(
  lists: { language: string }[],
  current: string,
): string[] {
  const languages = new Set<string>([current]);
  for (const list of lists) languages.add(list.language);
  return [...languages].sort((left, right) =>
    promptLanguageLabel(left).localeCompare(promptLanguageLabel(right)),
  );
}

/**
 * What a room switching to `language` should have selected.
 *
 * Lists cannot span languages, so nothing carries over: the previous selection
 * and any bearer codes that authorized it belong to the language being left.
 */
export function selectionForLanguage(
  lists: { slug: string; language: string }[],
  language: string,
): string[] {
  const first = lists.find((list) => list.language === language);
  return first ? [first.slug] : [];
}
