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

/**
 * What each language calls itself, capitalized the way that language does it:
 * German capitalizes its nouns, Dutch its language names, the Romance
 * languages neither.
 *
 * This is what a picker shows. Somebody looking for their own language is
 * looking for the word they use for it, and "German" is of no help to anyone
 * who would have searched for "Deutsch". The English name stays for the prose
 * around it, which is written in English (N-09 keeps the interface that way).
 */
export const PROMPT_LANGUAGE_ENDONYMS: Record<PromptLanguage, string> = {
  de: "Deutsch",
  en: "English",
  es: "español",
  fr: "français",
  it: "italiano",
  nl: "Nederlands",
  pt: "português",
};

export function promptLanguageLabel(language: string): string {
  return PROMPT_LANGUAGE_LABELS[language as PromptLanguage] ?? language;
}

export function promptLanguageEndonym(language: string): string {
  return PROMPT_LANGUAGE_ENDONYMS[language as PromptLanguage] ?? language;
}

/** Every supported language, in the order a picker should list them. */
export const SUPPORTED_PROMPT_LANGUAGES = (
  Object.keys(PROMPT_LANGUAGE_LABELS) as PromptLanguage[]
).sort((left, right) =>
  promptLanguageEndonym(left).localeCompare(promptLanguageEndonym(right)),
);

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
): PromptLanguage[] {
  const languages = new Set<string>([current]);
  for (const list of lists) languages.add(list.language);
  return SUPPORTED_PROMPT_LANGUAGES.filter((language) => languages.has(language));
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
  const inLanguage = lists.filter((list) => list.language === language);
  // That language's Standard list, which is where a room in it starts
  // (R-PROMPT-02) - not whichever list the catalogue happened to return
  // first, which is alphabetical and so lands on Extended.
  const standard = inLanguage.find((list) => list.slug.endsWith("_standard"));
  const chosen = standard ?? inLanguage[0];
  return chosen ? [chosen.slug] : [];
}
