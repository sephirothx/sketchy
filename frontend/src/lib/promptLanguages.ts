import type {
  GameEndedPayload,
  PromptLanguage,
  PromptListLanguage,
  PromptSpellings,
  RoomLanguage,
} from "../types";
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

/** BCP-47 "multiple languages": a mixed-language room (#1182), where each seat
plays in its own. Players see it as **Mixed** (GLOSSARY). */
export const MIXED_PROMPT_LANGUAGE = "mul";

/** Whether a list is one of the Standard lists: the same concepts in every
language (R-PROMPT-01), which is what a mixed room can play. */
function isStandard(list: { slug: string; isBundled?: boolean }): boolean {
  return list.slug.endsWith("_standard") && list.isBundled !== false;
}

/** Whether a room in `roomLanguage` can pick `list`: one in its own language,
or in none at all (R-PROMPT-02). A mixed room (R-PROMPT-13) takes lists in no
language and Standard - shown once, in `playLanguage`, since choosing any
language's Standard is choosing all of them. */
export function isPlayableIn(
  list: { slug: string; language: string; isBundled?: boolean },
  roomLanguage: string,
  playLanguage: string = "en",
): boolean {
  if (list.language === AGNOSTIC_PROMPT_LANGUAGE) return true;
  if (roomLanguage === MIXED_PROMPT_LANGUAGE) {
    return isStandard(list) && list.language === playLanguage;
  }
  return list.language === roomLanguage;
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
  if (language === MIXED_PROMPT_LANGUAGE) return ui.languagePicker.mixed;
  try {
    const name = new Intl.DisplayNames([interfaceLocale()], { type: "language" }).of(language);
    if (name && name !== language) return name;
  } catch {
    // A code the engine refuses falls through to the table.
  }
  return PROMPT_LANGUAGE_LABELS[language as PromptLanguage] ?? language;
}

export function promptLanguageEndonym(language: string): string {
  // "Any language" and "Mixed" are not languages with names for themselves.
  if (language === AGNOSTIC_PROMPT_LANGUAGE) return ui.languagePicker.anyLanguage;
  if (language === MIXED_PROMPT_LANGUAGE) return ui.languagePicker.mixed;
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
  lists: { slug: string; language: string; isBundled?: boolean }[],
  current: string,
): RoomLanguage[] {
  const languages = new Set<string>([current]);
  for (const list of lists) languages.add(list.language);
  const offered: RoomLanguage[] = SUPPORTED_PROMPT_LANGUAGES.filter(
    (language) => languages.has(language),
  );
  // Mixed, last, once Standard is there in every language to play (#1182).
  const standard = new Set(lists.filter(isStandard).map((list) => list.language));
  if (
    current === MIXED_PROMPT_LANGUAGE
    || SUPPORTED_PROMPT_LANGUAGES.every((language) => standard.has(language))
  ) {
    offered.push(MIXED_PROMPT_LANGUAGE);
  }
  return offered;
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
  lists: { slug: string; language: string; isBundled?: boolean }[],
  language: string,
  carried: readonly string[] = [],
  playLanguage: string = "en",
): string[] {
  const inLanguage = language === MIXED_PROMPT_LANGUAGE
    // A mixed room starts on Standard, shown in the language its host plays.
    ? lists.filter((list) => isPlayableIn(list, language, playLanguage)
      && list.language !== AGNOSTIC_PROMPT_LANGUAGE)
    : lists.filter((list) => list.language === language);
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
  lists: { slug: string; language: string; isBundled?: boolean }[],
  language: string,
  selected: readonly string[],
  playLanguage: string = "en",
): string[] {
  const playable = new Set(
    lists
      .filter((list) => isPlayableIn(list, language, playLanguage))
      .map((list) => list.slug),
  );
  const kept = selected.filter((slug) => playable.has(slug));
  return kept.length > 0 ? kept : selectionForLanguage(lists, language, [], playLanguage);
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

/** A payload naming a prompt, as this seat reads it: a mixed-language room
(#1182) sends every spelling in `prompts` beside the drawer's `prompt`, and
each client shows its own seat's. Everywhere else `prompt` is everyone's. */
export function spelledForSeat<T extends { prompt: string; prompts?: PromptSpellings }>(
  entry: T,
  seatLanguage: PromptLanguage | null,
): T {
  const own = seatLanguage ? entry.prompts?.[seatLanguage] : undefined;
  return own ? { ...entry, prompt: own } : entry;
}

/** A finished game's recap and highlights, each prompt as this seat reads it. */
export function gameEndSpelledForSeat<T extends GameEndedPayload>(
  payload: T,
  seatLanguage: PromptLanguage | null,
): T {
  return {
    ...payload,
    drawings: payload.drawings.map((entry) => spelledForSeat(entry, seatLanguage)),
    highlights: payload.highlights?.map((highlight) => (
      "prompt" in highlight ? spelledForSeat(highlight, seatLanguage) : highlight
    )),
  };
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
  // Your language first, then mixed rooms - which play you in it (#1182) -
  // then everything else.
  const rank = (room: T) =>
    room.promptLanguage === language ? 0 : room.promptLanguage === MIXED_PROMPT_LANGUAGE ? 1 : 2;
  return [...rooms].sort((left, right) => rank(left) - rank(right));
}
