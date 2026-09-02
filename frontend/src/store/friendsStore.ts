import { create } from "zustand";

import { NO_FRIENDS, type FriendLists } from "../lib/friends";
import {
  acceptFriend,
  listFriends,
  removeFriend,
  requestFriend,
} from "../lib/friendsApi";

interface FriendsStore {
  lists: FriendLists;
  loaded: boolean;
  /** The account currently being acted on, so one row can show it is busy. */
  pending: string | null;
  refresh: () => Promise<void>;
  add: (userId: string) => Promise<void>;
  accept: (userId: string) => Promise<void>;
  remove: (userId: string) => Promise<void>;
  reset: () => void;
}

/** Every mutation refetches rather than patching locally.

The server decides what a request became — a new pending row, an acceptance of
one that was already waiting, or deliberately nothing at all — and it answers
the last two identically on purpose. A local patch would have to guess, and
would guess wrong exactly where the guess matters. The lists are small and the
call is a button press. */
async function afterMutating(set: (partial: Partial<FriendsStore>) => void) {
  try {
    set({ lists: await listFriends(), loaded: true });
  } finally {
    set({ pending: null });
  }
}

export const useFriendsStore = create<FriendsStore>((set, get) => ({
  lists: NO_FRIENDS,
  loaded: false,
  pending: null,
  refresh: async () => {
    try {
      set({ lists: await listFriends(), loaded: true });
    } catch {
      // A guest gets a 403 here, which is the ordinary case rather than a
      // fault: they simply have no friends list, and every control that would
      // use one is hidden anyway.
      set({ lists: NO_FRIENDS, loaded: true });
    }
  },
  add: async (userId) => {
    if (get().pending) return;
    set({ pending: userId });
    try {
      await requestFriend(userId);
    } catch {
      // Refetching below is what corrects the row either way.
    }
    await afterMutating(set);
  },
  accept: async (userId) => {
    if (get().pending) return;
    set({ pending: userId });
    try {
      await acceptFriend(userId);
    } catch {
      /* as above */
    }
    await afterMutating(set);
  },
  remove: async (userId) => {
    if (get().pending) return;
    set({ pending: userId });
    try {
      await removeFriend(userId);
    } catch {
      /* as above */
    }
    await afterMutating(set);
  },
  reset: () => set({ lists: NO_FRIENDS, loaded: false, pending: null }),
}));
