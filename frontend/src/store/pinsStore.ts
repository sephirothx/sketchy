import { useEffect } from "react";
import { create } from "zustand";

import { fetchProfilePins, setMyPins } from "../lib/profile";
import { useAuthStore } from "./authStore";

interface PinsStore {
  /** Whose shelf `turnIds` describes, so a second account never inherits the first's. */
  ownerId: string | null;
  /** The signed-in player's pinned turn ids, in shelf order. */
  turnIds: string[];
  /** Whether `turnIds` is an answer about `ownerId` rather than a starting value. */
  loaded: boolean;
  /** A write is in flight; every Pin control waits on the same one. */
  pending: boolean;
  /** Read the shelf for `accountId`; `null` forgets it. */
  load: (accountId: string | null) => Promise<void>;
  /** Write the whole ordered list (R-PIN-02) and keep the server's answer. */
  replace: (turnIds: string[]) => Promise<void>;
  /** Keep a list something else already wrote - the profile shelf's own controls. */
  adopt: (turnIds: string[]) => void;
  reset: () => void;
}

/**
 * The signed-in player's pins, shared by every place a Pin control appears -
 * the game-over recap, the profile's turn table, the shelf - so pressing it in
 * one place is pressed in all of them. Ids only: the entries the shelf shows
 * are the profile page's to fetch, since only it renders them.
 */
export const usePinsStore = create<PinsStore>((set, get) => ({
  ownerId: null,
  turnIds: [],
  loaded: false,
  pending: false,
  load: async (accountId) => {
    if (!accountId) {
      set({ ownerId: null, turnIds: [], loaded: false });
      return;
    }
    // Claimed before the answer arrives, so a second call for the same
    // account while this one is out does not fetch twice.
    set({ ownerId: accountId, turnIds: [], loaded: false });
    try {
      const shelf = await fetchProfilePins(accountId);
      if (get().ownerId !== accountId) return;
      set({ turnIds: shelf.pins.map((pin) => pin.turnId), loaded: true });
    } catch {
      if (get().ownerId !== accountId) return;
      set({ turnIds: [], loaded: false });
    }
  },
  replace: async (turnIds) => {
    set({ pending: true });
    try {
      const answer = await setMyPins(turnIds);
      set({ turnIds: answer.pins.map((pin) => pin.turnId), loaded: true });
    } finally {
      set({ pending: false });
    }
  },
  adopt: (turnIds) => set({ turnIds: [...turnIds], loaded: true }),
  reset: () => set({ ownerId: null, turnIds: [], loaded: false, pending: false }),
}));

/**
 * The store, kept in step with the signed-in account: loaded once per
 * registered account, forgotten when there is none. Guests hold no shelf and
 * are not asked for one.
 */
export function useMyPins(): PinsStore {
  const user = useAuthStore((s) => s.user);
  const accountId = user && !user.isAnonymous ? user.id : null;
  const ownerId = usePinsStore((s) => s.ownerId);
  useEffect(() => {
    if (ownerId === accountId) return;
    void usePinsStore.getState().load(accountId);
  }, [accountId, ownerId]);
  return usePinsStore();
}
