/**
 * Favorites (#440): the six drawings a profile chose to show, and the
 * list arithmetic behind the owner's controls.
 *
 * The server takes the whole ordered shelf on every write (R-PIN-02), so the
 * helpers here produce the next list rather than a "move" or "remove"
 * command: favorite, unfavorite and reorder are the same request with a different
 * list. Pure, so the node suite can hold them to their edges without a DOM.
 */
import type { DrawingRecapMetadata } from "../types";

/** The cap, mirrored from `PROFILE_FAVORITE_SLOTS`: the whole shelf, never a page of it. */
export const FAVORITE_SLOTS = 6;

export interface FavoriteReaction {
  seatId: string;
  emoji: string;
}

/** One entry of `GET /api/users/{id}/favorites`: a game-detail turn where the two
    overlap, credited through the frozen drawer snapshot, and no game id. */
export interface ProfileFavorite {
  turnId: string;
  roundNumber: number;
  turnNumber: number;
  drawerDisplayName: string;
  drawerNameColor: string | null;
  drawerIsAnonymous: boolean;
  prompt: string;
  strokeCount: number;
  /** The reactions given by a seat, named; outsiders' are only in the counts. */
  reactions: FavoriteReaction[];
  /** Every reaction by code, the seatless ones included (R-REACT-05). */
  reactionCounts: Record<string, number>;
  /** The viewer's own pick, and whether the drawing is theirs: what the picker needs. */
  myReaction: string | null;
  drawnByMe: boolean;
}

export type ShelfPresence = "absent" | "empty" | "shelf";

/**
 * Whether the profile shows a shelf at all. Signed out is *absent*, not
 * empty (R-PIN-06): the server would answer 404 and the page must not imply
 * there is nothing favorited. The owner alone sees an empty shelf, because it is
 * the one place that can tell them how to fill it.
 */
export function shelfPresence(input: {
  viewerSignedIn: boolean;
  isOwner: boolean;
  count: number;
}): ShelfPresence {
  if (!input.viewerSignedIn) return "absent";
  if (input.count > 0) return "shelf";
  return input.isOwner ? "empty" : "absent";
}

export type FavoriteEligibility = "offered" | "hidden";

/**
 * Whether a Favorite control is offered at all (R-PIN-09): the write would be
 * refused for a guest, a spectator or a drawing that was not kept, and - since
 * a favorite is a share (R-PIN-03) - for a drawing the viewer may not share: a
 * private game's that is not theirs, a blank one, or one its drawer took out
 * of the Gallery. A control that cannot work is not shown. Guests are not
 * told here how to become able to: the reaction control beside every drawing
 * already says it once.
 */
export function favoriteEligibility(input: {
  isRegistered: boolean;
  isSpectator?: boolean;
  isPublicGame: boolean;
  open: boolean;
  isDrawer?: boolean;
  blank?: boolean;
  withdrawn?: boolean;
}): FavoriteEligibility {
  if (!input.isRegistered || input.isSpectator || !input.open || input.blank) {
    return "hidden";
  }
  if (!input.isDrawer && (!input.isPublicGame || input.withdrawn)) return "hidden";
  return "offered";
}

export function isFavorite(turnIds: readonly string[], turnId: string): boolean {
  return turnIds.includes(turnId);
}

export function shelfIsFull(turnIds: readonly string[]): boolean {
  return turnIds.length >= FAVORITE_SLOTS;
}

/** The list with `turnId` appended, or `null` when it is already there or the shelf is full. */
export function withFavorite(turnIds: readonly string[], turnId: string): string[] | null {
  if (isFavorite(turnIds, turnId) || shelfIsFull(turnIds)) return null;
  return [...turnIds, turnId];
}

export function withoutFavorite(turnIds: readonly string[], turnId: string): string[] {
  return turnIds.filter((id) => id !== turnId);
}

/**
 * The list with the entry at `index` moved by `delta` places. Out of range
 * on either side returns the list unchanged, so a button at an edge is safe
 * to press and simply does nothing; the component disables it besides.
 */
export function moveFavorite(turnIds: readonly string[], index: number, delta: number): string[] {
  const target = index + delta;
  if (index < 0 || index >= turnIds.length || target < 0 || target >= turnIds.length) {
    return [...turnIds];
  }
  const next = [...turnIds];
  const [moved] = next.splice(index, 1);
  next.splice(target, 0, moved);
  return next;
}

/** Shelf entries as the recap gallery reads them, in shelf order. */
export function favoritesAsRecapEntries(favorites: readonly ProfileFavorite[]): DrawingRecapMetadata[] {
  return favorites.map((favorite, index) => ({
    index,
    turnId: favorite.turnId,
    roundNumber: favorite.roundNumber,
    turnNumber: favorite.turnNumber,
    // The shelf knows no seat: the byline is the snapshot, and whether the
    // viewer drew it comes from the server (`drawnByMe`), so the gallery
    // never needs a drawer id to compare against.
    drawerId: "",
    drawerNickname: favorite.drawerDisplayName,
    drawerNameColor: favorite.drawerNameColor ?? undefined,
    drawerIsAnonymous: favorite.drawerIsAnonymous,
    prompt: favorite.prompt,
    actionCount: favorite.strokeCount,
    available: true,
  }));
}
