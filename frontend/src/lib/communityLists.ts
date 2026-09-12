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
