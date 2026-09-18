import { create } from "zustand";

/**
 * The one way into a room that is in flight, whoever started it (#589).
 *
 * A socket holds one seat, and every entry releases the seat it held before
 * (R-ROOM-08). Two entries in flight at once - Quick play walking its
 * candidates while a friend's invitation is accepted, say - release each
 * other's seats and race for the session and the route, and the loser can
 * leave the player looking at a room they are no longer in.
 *
 * So entry is a lock, and it lives here rather than in a page: the lobby's
 * cards, codes and Quick play, the create form, a friend's invitation and the
 * online list's Join all take it, and it outlives the lobby unmounting under
 * an answer that has not arrived yet. Whoever holds it gets a token; only
 * that token releases it, so a late `finally` cannot free somebody else's.
 */

export type RoomEntryMode = "join" | "spectate";

export interface PendingRoomEntry {
  /** What started it, for the control that should read "Joining…". */
  key: string;
  mode: RoomEntryMode;
  token: number;
}

interface RoomEntryStore {
  pending: PendingRoomEntry | null;
  /** Take the lock, or get null when an entry is already in flight. */
  begin: (key: string, mode?: RoomEntryMode) => number | null;
  /** Release it - only with the token `begin` handed out. */
  end: (token: number) => void;
}

let nextToken = 1;

export const useRoomEntryStore = create<RoomEntryStore>((set, get) => ({
  pending: null,
  begin: (key, mode = "join") => {
    if (get().pending) return null;
    const token = nextToken++;
    set({ pending: { key, mode, token } });
    return token;
  },
  end: (token) => {
    if (get().pending?.token === token) set({ pending: null });
  },
}));
