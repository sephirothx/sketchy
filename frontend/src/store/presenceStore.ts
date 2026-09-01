import { create } from "zustand";

import {
  EMPTY_PRESENCE,
  applyDelta,
  applySnapshot,
  type PresenceState,
} from "../lib/lobbyPresence";

interface PresenceStore {
  presence: PresenceState;
  /** Replace the list: the answer to `watch_lobby`, and every resync. */
  receiveSnapshot: (payload: unknown) => void;
  /** Apply one delta, or mark the store for a resync if one was missed. */
  receiveDelta: (payload: unknown) => void;
  /** Back to nothing, on leaving the lobby or losing the socket. */
  reset: () => void;
}

export const usePresenceStore = create<PresenceStore>((set) => ({
  presence: EMPTY_PRESENCE,
  receiveSnapshot: (payload) => set({ presence: applySnapshot(payload) }),
  // `applyDelta` returns the state it was given when there is nothing to do -
  // a duplicate, a message from before a resync, an unreadable one - so an
  // identical reference here is what keeps the panel from re-rendering on
  // every tick of a quiet server.
  receiveDelta: (payload) =>
    set((state) => {
      const next = applyDelta(state.presence, payload);
      return next === state.presence ? state : { presence: next };
    }),
  reset: () => set({ presence: EMPTY_PRESENCE }),
}));
