import type { PromptLanguage, PromptListLanguage } from "../types";
import { interfaceLocale, ui } from "../content/ui/index.ts";

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

/** BCP-47 "no linguistic content": a list in no language at all (#821), such
as Pokémon or brands. Players see it as **Any language** (GLOSSARY). */
export const AGNOSTIC_PROMPT_LANGUAGE = "zxx";

/** Whether a room in `roomLanguage` can pick a list in `listLanguage`: its
own language, or none at all (R-PROMPT-02). */
export function isPlayableIn(listLanguage: string, roomLanguage: string): boolean {
  return listLanguage === roomLanguage || listLanguage === AGNOSTIC_PROMPT_LANGUAGE;
}

/** The language to search and sort a list's prompts in. A list in no language
has no collation of its own, so it takes the reader's. */
export function contentLocale(language: PromptListLanguage | string): string {
  return language === AGNOSTIC_PROMPT_LANGUAGE ? interfaceLocale() : language;
}

/** A prompt language as the prose around it names it: in the interface's own
language, so a German reader is told about "Englisch". The browser already
knows every one of these names; the table is only for an engine that does not. */
export function promptLanguageLabel(language: string): string {
  if (language === AGNOSTIC_PROMPT_LANGUAGE) return ui.languagePicker.anyLanguage;
  try {
    const name = new Intl.DisplayNames([interfaceLocale()], { type: "language" }).of(language);
    if (name && name !== language) return name;
  } catch {
    // A code the engine refuses falls through to the table.
  }
  return PROMPT_LANGUAGE_LABELS[language as PromptLanguage] ?? language;
}

export function promptLanguageEndonym(language: string): string {
  // "Any language" is not a language with a name for itself.
  if (language === AGNOSTIC_PROMPT_LANGUAGE) return ui.languagePicker.anyLanguage;
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
 * A list in a language cannot follow the room into another one, so none of
 * those carries over. A list in no language (#821) is played in any room, so
 * whichever of those were in `carried` stay chosen beside the new language's
 * Standard list.
 */
export function selectionForLanguage(
  lists: { slug: string; language: string }[],
  language: string,
  carried: readonly string[] = [],
): string[] {
  const inLanguage = lists.filter((list) => list.language === language);
  // That language's Standard list, which is where a room in it starts
  // (R-PROMPT-02) - not whichever list the catalogue happened to return
  // first, which is alphabetical and so lands on Extended.
  const standard = inLanguage.find((list) => list.slug.endsWith("_standard"));
  const chosen = standard ?? inLanguage[0];
  const agnostic = new Set(
    lists
      .filter((list) => list.language === AGNOSTIC_PROMPT_LANGUAGE)
      .map((list) => list.slug),
  );
  return [
    ...(chosen ? [chosen.slug] : []),
    ...carried.filter((slug) => agnostic.has(slug)),
  ];
}

/**
 * The selection a room in `language` should hold, given what it holds now.
 *
 * The two are set from different places - the language from the player's own
 * preference, the lists from the catalogue - and nothing kept them in step:
 * a German player opened the create form declaring German while the selection
 * still said `english_standard`, which the server refuses. Anything already
 * in the language is kept, as is any list in no language at all (#821), and a
 * selection with nothing left in it falls back to that language's Standard
 * list.
 */
export function reconcileSelectionForLanguage(
  lists: { slug: string; language: string }[],
  language: string,
  selected: readonly string[],
): string[] {
  const playable = new Set(
    lists.filter((list) => isPlayableIn(list.language, language)).map((list) => list.slug),
  );
  const kept = selected.filter((slug) => playable.has(slug));
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
