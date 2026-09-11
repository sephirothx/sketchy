import type { PromptLanguage } from "../types";
import { interfaceLocale } from "../content/ui/index.ts";

/** Not copy: English names, the fallback for an engine without
`Intl.DisplayNames` (see `promptLanguageLabel`). */
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
 * who would have searched for "Deutsch". The prose around it names the
 * language in the reader's interface language instead (`promptLanguageLabel`).
 *
 * Not copy: each name is in its own language whatever the reader's.
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

/** A prompt language as the prose around it names it: in the interface's own
language, so a German reader is told about "Englisch". The browser already
knows every one of these names; the table is only for an engine that does not. */
export function promptLanguageLabel(language: string): string {
  try {
    const name = new Intl.DisplayNames([interfaceLocale()], { type: "language" }).of(language);
    if (name && name !== language) return name;
  } catch {
    // A code the engine refuses falls through to the table.
  }
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

/**
 * The selection a room in `language` should hold, given what it holds now.
 *
 * The two are set from different places - the language from the player's own
 * preference, the lists from the catalogue - and nothing kept them in step:
 * a German player opened the create form declaring German while the selection
 * still said `english_standard`, which the server refuses. Anything already
 * in the language is kept, and a selection with nothing left in it falls back
 * to that language's Standard list.
 */
export function reconcileSelectionForLanguage(
  lists: { slug: string; language: string }[],
  language: string,
  selected: readonly string[],
): string[] {
  const inLanguage = new Set(
    lists.filter((list) => list.language === language).map((list) => list.slug),
  );
  const kept = selected.filter((slug) => inLanguage.has(slug));
  return kept.length > 0 ? kept : selectionForLanguage(lists, language);
}

/**
 * The language this visitor plays in, as the browser reports it.
 *
 * A signed-in player's stored setting wins over this; it is what a visitor
 * with no account has, and what seeds the setting when they register. An
 * unsupported or absent list falls back to English rather than to nothing,
 * because every screen this feeds has to render either way.
 */
export function preferredPromptLanguage(
  candidates: readonly string[] | undefined,
): PromptLanguage {
  for (const candidate of candidates ?? []) {
    const tag = candidate.trim().toLowerCase();
    if (!tag) continue;
    const base = tag.split("-", 1)[0];
    if (base in PROMPT_LANGUAGE_LABELS) return base as PromptLanguage;
  }
  return "en";
}

/**
 * Your language first, everything else in the order it arrived.
 *
 * Nothing is hidden: a lobby filtered to one language looks empty while rooms
 * are open, which is a worse answer than a longer list. `sort` is stable, so
 * the server's ordering survives inside each group.
 */
export function sortRoomsByLanguage<T extends { promptLanguage: string }>(
  rooms: readonly T[],
  language: string,
): T[] {
  return [...rooms].sort((left, right) =>
    Number(right.promptLanguage === language)
    - Number(left.promptLanguage === language),
  );
}
