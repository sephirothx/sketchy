/**
 * Pinned drawings (#440): the six drawings a profile chose to show, and the
 * list arithmetic behind the owner's controls.
 *
 * The server takes the whole ordered shelf on every write (R-PIN-02), so the
 * helpers here produce the next list rather than a "move" or "remove"
 * command: pin, unpin and reorder are the same request with a different
 * list. Pure, so the node suite can hold them to their edges without a DOM.
 */
import type { DrawingRecapMetadata } from "../types";

/** The cap, mirrored from `PROFILE_PIN_SLOTS`: the whole shelf, never a page of it. */
export const PINNED_DRAWING_SLOTS = 6;

export interface PinnedReaction {
  seatId: string;
  emoji: string;
}

/** One entry of `GET /api/users/{id}/pins`: a game-detail turn where the two
    overlap, credited through the frozen drawer snapshot, and no game id. */
export interface ProfilePin {
  turnId: string;
  roundNumber: number;
  turnNumber: number;
  drawerDisplayName: string;
  drawerNameColor: string | null;
  drawerIsAnonymous: boolean;
  prompt: string;
  strokeCount: number;
  reactions: PinnedReaction[];
}

export type ShelfPresence = "absent" | "empty" | "shelf";

/**
 * Whether the profile shows a shelf at all. Signed out is *absent*, not
 * empty (R-PIN-06): the server would answer 404 and the page must not imply
 * there is nothing pinned. The owner alone sees an empty shelf, because it is
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

export function isPinned(turnIds: readonly string[], turnId: string): boolean {
  return turnIds.includes(turnId);
}

export function shelfIsFull(turnIds: readonly string[]): boolean {
  return turnIds.length >= PINNED_DRAWING_SLOTS;
}

/** The list with `turnId` appended, or `null` when it is already there or the shelf is full. */
export function withPin(turnIds: readonly string[], turnId: string): string[] | null {
  if (isPinned(turnIds, turnId) || shelfIsFull(turnIds)) return null;
  return [...turnIds, turnId];
}

export function withoutPin(turnIds: readonly string[], turnId: string): string[] {
  return turnIds.filter((id) => id !== turnId);
}

/**
 * The list with the entry at `index` moved by `delta` places. Out of range
 * on either side returns the list unchanged, so a button at an edge is safe
 * to press and simply does nothing; the component disables it besides.
 */
export function movePin(turnIds: readonly string[], index: number, delta: number): string[] {
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
export function pinsAsRecapEntries(pins: readonly ProfilePin[]): DrawingRecapMetadata[] {
  return pins.map((pin, index) => ({
    index,
    turnId: pin.turnId,
    roundNumber: pin.roundNumber,
    turnNumber: pin.turnNumber,
    // The shelf knows no seat: the byline is the snapshot, and nobody on
    // it reacts, so the gallery never needs a drawer id to compare against.
    drawerId: "",
    drawerNickname: pin.drawerDisplayName,
    drawerNameColor: pin.drawerNameColor ?? undefined,
    prompt: pin.prompt,
    actionCount: pin.strokeCount,
    available: true,
  }));
}
