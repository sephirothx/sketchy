/**
 * The Gallery (#524): every kept drawing from a public game, for anyone
 * signed in (R-GAL-01, R-GAL-02).
 *
 * The filters live in the URL so an order is a link, and the parsing lives
 * here so it has somewhere to be tested. Pure apart from the two fetchers,
 * so the node suite can hold the parsing and the recap mapping to their
 * edges without a DOM.
 */
import { apiBinaryRequest, apiRequest } from "./api.ts";
import type { DrawingRecapMetadata } from "../types";

export type GallerySort = "hot" | "new" | "top";
export type GalleryWindow = "all" | "month" | "week";

/** One entry of `GET /api/gallery`: what a pin publishes and nothing more
    (R-GAL-03) - the frozen drawer snapshot, the prompt, the counts, and
    deliberately no game id. */
export interface GalleryEntry {
  turnId: string;
  roundNumber: number;
  turnNumber: number;
  drawerDisplayName: string;
  drawerNameColor: string | null;
  drawerIsAnonymous: boolean;
  prompt: string;
  strokeCount: number;
  /** When the game finished, as an ISO timestamp: the New order's key. */
  finishedAt: string;
  /** Every reaction by code, the seatless ones included (R-REACT-05). */
  reactionCounts: Record<string, number>;
  /** The viewer's own pick, and whether the drawing is theirs: what the picker needs. */
  myReaction: string | null;
  drawnByMe: boolean;
}

export interface GalleryPage {
  entries: GalleryEntry[];
  nextCursor: string | null;
}

export interface GalleryFilters {
  sort: GallerySort;
  /** Only meaningful under Top (R-GAL-04); kept as parsed so switching
      Top → New → Top comes back to the same window. */
  window: GalleryWindow;
}

export const DEFAULT_GALLERY_FILTERS: GalleryFilters = { sort: "hot", window: "all" };

const SORTS = new Set<GallerySort>(["hot", "new", "top"]);
const WINDOWS = new Set<GalleryWindow>(["all", "month", "week"]);

export function galleryFiltersFromParams(params: URLSearchParams): GalleryFilters {
  const sort = params.get("sort");
  const window = params.get("window");
  return {
    // An unknown value reads as the default rather than as an error: the
    // only way to hold one is to have edited the link, and a page that
    // refuses to render is worse than one that shows what is hot.
    sort: sort && SORTS.has(sort as GallerySort) ? (sort as GallerySort) : DEFAULT_GALLERY_FILTERS.sort,
    window: window && WINDOWS.has(window as GalleryWindow)
      ? (window as GalleryWindow)
      : DEFAULT_GALLERY_FILTERS.window,
  };
}

export function paramsFromGalleryFilters(filters: GalleryFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.sort !== DEFAULT_GALLERY_FILTERS.sort) params.set("sort", filters.sort);
  if (filters.window !== DEFAULT_GALLERY_FILTERS.window) params.set("window", filters.window);
  return params;
}

/** One page of the Gallery, in the asked order (R-GAL-04). A session is
    required: without one the server answers `account_required`. */
export function fetchGallery(
  filters: GalleryFilters,
  cursor: string | null,
): Promise<GalleryPage> {
  const params = new URLSearchParams({ sort: filters.sort, window: filters.window });
  if (cursor) params.set("cursor", cursor);
  return apiRequest<GalleryPage>(`/api/gallery?${params.toString()}`);
}

/**
 * A Gallery drawing's bytes through the gallery door (R-GAL-06): the third
 * route beside the participant's and the pin's, and every refusal a 404.
 */
export function fetchGalleryDrawing(turnId: string): Promise<ArrayBuffer> {
  return apiBinaryRequest(`/api/gallery/${encodeURIComponent(turnId)}/drawing`);
}

/** Gallery entries as the recap gallery reads them, in page order. */
export function galleryEntriesAsRecap(entries: readonly GalleryEntry[]): DrawingRecapMetadata[] {
  return entries.map((entry, index) => ({
    index,
    turnId: entry.turnId,
    roundNumber: entry.roundNumber,
    turnNumber: entry.turnNumber,
    // The Gallery knows no seat: the byline is the snapshot, and whether the
    // viewer drew it comes from the server (`drawnByMe`), so the recap never
    // needs a drawer id to compare against.
    drawerId: "",
    drawerNickname: entry.drawerDisplayName,
    drawerNameColor: entry.drawerNameColor ?? undefined,
    prompt: entry.prompt,
    actionCount: entry.strokeCount,
    available: true,
  }));
}

/**
 * The lobby's **This week** shelf (R-GAL-07): Top-week's first six, from a
 * snapshot the server recomputes at most once a minute. One read on open;
 * the browser revalidates the validator it was given, never polls.
 */
export function fetchThisWeek(): Promise<{ entries: GalleryEntry[] }> {
  return apiRequest("/api/gallery/week");
}

export type GalleryAgeUnit = "minute" | "hour" | "day";

/**
 * How long ago a drawing's game finished, in the unit a feed reads in: a
 * fresh one in minutes, an old one in days, never a clock time. `null` for
 * under a minute, which the caller words as "just now".
 */
export function galleryAge(
  finishedAt: string,
  now: Date = new Date(),
): { count: number; unit: GalleryAgeUnit } | null {
  const seconds = Math.max(0, (now.getTime() - new Date(finishedAt).getTime()) / 1000);
  if (seconds < 60) return null;
  const units: [number, GalleryAgeUnit][] = [
    [60, "minute"],
    [60, "hour"],
    [24, "day"],
  ];
  let value = seconds;
  let unit: GalleryAgeUnit = "minute";
  for (const [size, name] of units) {
    if (value < size) break;
    value /= size;
    unit = name;
  }
  return { count: Math.floor(value), unit };
}
