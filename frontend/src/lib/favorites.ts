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
import { isSlotChar, maskedWords, type MaskedSegment } from "./maskedPrompt.ts";

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
 * The list with `turnId` in it or out of it, as a press asked - not flipped
 * from whatever the list holds. A mutation can run on a list the press never
 * saw (the queue, or a reread after a 404), and a toggle computed there
 * would take off a drawing the player just asked to add. Already as asked
 * returns the list unchanged; `null` only for an add to a full shelf.
 */
export function favoriteSetTo(turnIds: readonly string[], turnId: string, favorited: boolean): string[] | null {
  if (isFavorite(turnIds, turnId) === favorited) return [...turnIds];
  return favorited ? withFavorite(turnIds, turnId) : withoutFavorite(turnIds, turnId);
}

/**
 * A shelf the owner arranged, laid over the list as it stands now. `asked`
 * was made from `base`; by the time it is sent the list may have gained a
 * favorite from another control, or lost one the server dropped. What the
 * owner took off stays off, what they kept keeps their order if it is still
 * there, and anything they never saw follows at the end.
 */
export function rebaseFavorites(
  asked: readonly string[],
  base: readonly string[],
  current: readonly string[],
): string[] {
  const kept = asked.filter((id) => current.includes(id));
  const unseen = current.filter((id) => !asked.includes(id) && !base.includes(id));
  return [...kept, ...unseen];
}

/**
 * The list with `turnId` put at `index`, the others closing up around it: what
 * a drag, or the arrow keys on a lifted drawing, leaves the shelf as. Unknown
 * ids and an out-of-range index return the list unchanged.
 */
export function moveFavoriteTo(turnIds: readonly string[], turnId: string, index: number): string[] {
  const from = turnIds.indexOf(turnId);
  if (from < 0 || index < 0 || index >= turnIds.length || index === from) return [...turnIds];
  const next = [...turnIds];
  next.splice(from, 1);
  next.splice(index, 0, turnId);
  return next;
}

/**
 * A prompt as a visitor first sees it on somebody's favorites (#1501): one
 * blank tile per letter, word breaks and punctuation kept, the way the game
 * masks it (`maskedPrompt.ts`), and the letters per run for the label. The
 * tiles say how long the word is - a hint, like the game's - and nothing else.
 */
export function hiddenPromptShape(prompt: string): { words: MaskedSegment[][]; counts: number[] } {
  const mask = Array.from(prompt, (ch) => (isSlotChar(ch) ? "_" : ch)).join("");
  const words = maskedWords(mask);
  const counts = words.flatMap((segments) =>
    segments.flatMap((segment) => (segment.kind === "tiles" ? [segment.chars.length] : [])),
  );
  return { words, counts };
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
