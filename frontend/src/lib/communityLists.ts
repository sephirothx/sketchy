import type { CommunityPromptListQuery } from "./promptLists";
import type { PromptLanguage } from "../types";

/** The catalogue's filters, carried in the URL so a filtered view is a link.
 *
 * Kept out of the page so the parsing has somewhere to be tested: a filter
 * that silently resets is the kind of thing nobody notices until they have
 * shared a link that shows something else. */
export interface CatalogueFilters {
  language: PromptLanguage | null;
  tags: string[];
  sort: "stars" | "newest";
  starred: boolean;
}

export const DEFAULT_FILTERS: CatalogueFilters = {
  language: null,
  tags: [],
  sort: "stars",
  starred: false,
};

const LANGUAGES = new Set(["de", "en", "es", "fr", "it", "nl", "pt"]);

export function filtersFromParams(params: URLSearchParams): CatalogueFilters {
  const language = params.get("language");
  const sort = params.get("sort");
  return {
    // An unknown value reads as "no filter" rather than as an error: the only
    // way to hold one is to have edited the link, and a catalogue that
    // refuses to render is worse than one that shows everything.
    language: language && LANGUAGES.has(language) ? (language as PromptLanguage) : null,
    tags: params.getAll("tag").filter(Boolean),
    sort: sort === "newest" ? "newest" : "stars",
    starred: params.get("starred") === "true",
  };
}

export function paramsFromFilters(filters: CatalogueFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.language) params.set("language", filters.language);
  for (const tag of filters.tags) params.append("tag", tag);
  if (filters.sort !== "stars") params.set("sort", filters.sort);
  if (filters.starred) params.set("starred", "true");
  return params;
}

export function isFiltered(filters: CatalogueFilters): boolean {
  return Boolean(
    filters.language || filters.tags.length > 0 || filters.starred,
  );
}

/** Toggling a tag keeps vocabulary order, so the URL of a given selection is
 * the same however it was arrived at. */
export function withTag(
  filters: CatalogueFilters,
  slug: string,
  vocabulary: readonly string[],
): CatalogueFilters {
  const held = new Set(filters.tags);
  if (held.has(slug)) held.delete(slug);
  else held.add(slug);
  return { ...filters, tags: vocabulary.filter((entry) => held.has(entry)) };
}

export function queryFromFilters(
  filters: CatalogueFilters,
  cursor: string | null,
): CommunityPromptListQuery {
  return {
    language: filters.language ?? undefined,
    tags: filters.tags,
    sort: filters.sort,
    starred: filters.starred || undefined,
    cursor,
  };
}

/** How many prompts the pane shows before offering the rest. Enough to judge
 * a list by, few enough that a 500-prompt list does not push the page away. */
export const PREVIEW_PROMPTS = 24;

/** A prompt reduced for matching: each character to its base letter, lower
 * cased in the list's own language.
 *
 * One code point in, one out - that is the whole design. Folding "é" through
 * NFD makes two, and lower-casing some capitals makes two more; either would
 * shift every index after it, and then a match found in the folded text would
 * be highlighted in the wrong place of the text the reader actually sees. */
export function foldForSearch(text: string, language: string): string[] {
  return [...text].map((character) => {
    const base = [...character.normalize("NFD")][0] ?? character;
    return [...base.toLocaleLowerCase(language)][0] ?? base;
  });
}

export interface PromptMatch {
  /** Code-point offsets into the prompt as written. */
  start: number;
  end: number;
}

/** Where a search first occurs in a prompt, ignoring case and accents - so
 * "brulee" finds "Crème brûlée", which is what a reader typing on a keyboard
 * without the accent means. An empty search matches nothing: a search box
 * nobody has typed in is not a search. */
export function findInPrompt(
  text: string,
  query: string,
  language: string,
): PromptMatch | null {
  const needle = foldForSearch(query.trim(), language);
  if (needle.length === 0) return null;
  const haystack = foldForSearch(text, language);
  for (let start = 0; start + needle.length <= haystack.length; start += 1) {
    if (needle.every((character, offset) => haystack[start + offset] === character)) {
      return { start, end: start + needle.length };
    }
  }
  return null;
}

export interface PromptGroup<T> {
  /** The letter a reader would look under - or "#" for anything else. */
  initial: string;
  entries: T[];
}

/** Prompts A-Z in the list's own language, under the letter each begins with.
 *
 * Sorted by that language's collation rather than by code point, because a
 * German reader expects Äpfel beside Apfel and not after Zebra. An accented
 * initial files under its base letter, as a printed index does - É with E, Ä
 * with A - so a letter never appears twice. A prompt that does not start with
 * a letter goes under "#". */
export function groupAlphabetically<T>(
  entries: readonly T[],
  textOf: (entry: T) => string,
  language: string,
): PromptGroup<T>[] {
  // Default sensitivity, not "base": base would call Apfel and Äpfel equal and
  // leave their order to whatever order they arrived in. The default ranks by
  // letter first and accent second, so the order is the same every time.
  const collator = new Intl.Collator(language, { numeric: true });
  const sorted = [...entries].sort((left, right) => collator.compare(textOf(left), textOf(right)));
  const groups: PromptGroup<T>[] = [];
  for (const entry of sorted) {
    const first = foldForSearch(textOf(entry).trim(), language)[0] ?? "";
    const initial = /\p{L}/u.test(first) ? first.toLocaleUpperCase(language) : "#";
    const last = groups.at(-1);
    if (last && last.initial === initial) last.entries.push(entry);
    else groups.push({ initial, entries: [entry] });
  }
  return groups;
}

/** Every page of a paged read, followed to its end.
 *
 * For a read whose whole answer is wanted at once, like the lists an account
 * starred: stopping at the first page drops the rest without a word, and the
 * rest is exactly what a shortlist ordered by popularity would lose - the
 * lists this account starred that few others did.
 *
 * `maxPages` guards against a cursor that never ends. Reaching it is reported
 * as `complete: false` rather than handed back as if it were everything,
 * because a partial answer that looks whole is the failure this exists to
 * prevent. */
export async function readEveryPage<T>(
  readPage: (cursor: string | null) => Promise<{ lists: T[]; nextCursor: string | null }>,
  maxPages: number,
): Promise<{ lists: T[]; complete: boolean }> {
  const lists: T[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < maxPages; page += 1) {
    const read = await readPage(cursor);
    lists.push(...read.lists);
    cursor = read.nextCursor;
    if (!cursor) return { lists, complete: true };
  }
  return { lists, complete: false };
}
