import { create } from "zustand";

import {
  NO_FRIENDS,
  NO_FRIEND_CHANGES,
  friendListChanges,
  type FriendLists,
  type FriendListChanges,
} from "../lib/friends";
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
  /** What moved on the last read, and a counter that says it is new.

  A counter rather than a flag somebody has to clear: two requests arriving in
  a row produce the same shape twice, and a consumer comparing the object
  would show the first and miss the second. */
  notices: FriendListChanges & { seq: number };
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
async function afterMutating(
  set: (partial: Partial<FriendsStore>) => void,
  get: () => FriendsStore,
) {
  try {
    absorb(set, get, await listFriends());
  } finally {
    set({ pending: null });
  }
}

/** Replace the lists, and say what moved.

The diff runs on every read rather than only on the socket event, because a
mutation refetches too and somebody else's request may have landed in between.
It is skipped before the first read has landed: everything is new then, and a
fresh tab is not the moment to announce a week of requests. */
function absorb(
  set: (partial: Partial<FriendsStore>) => void,
  get: () => FriendsStore,
  next: FriendLists,
) {
  const previous = get();
  if (!previous.loaded) {
    set({ lists: next, loaded: true });
    return;
  }
  const changes = friendListChanges(previous.lists, next);
  if (changes.arrived.length === 0 && changes.accepted.length === 0) {
    set({ lists: next });
    return;
  }
  set({
    lists: next,
    notices: { ...changes, seq: previous.notices.seq + 1 },
  });
}

export const useFriendsStore = create<FriendsStore>((set, get) => ({
  lists: NO_FRIENDS,
  loaded: false,
  pending: null,
  notices: { ...NO_FRIEND_CHANGES, seq: 0 },
  refresh: async () => {
    try {
      absorb(set, get, await listFriends());
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
    await afterMutating(set, get);
  },
  accept: async (userId) => {
    if (get().pending) return;
    set({ pending: userId });
    try {
      await acceptFriend(userId);
    } catch {
      /* as above */
    }
    await afterMutating(set, get);
  },
  remove: async (userId) => {
    if (get().pending) return;
    set({ pending: userId });
    try {
      await removeFriend(userId);
    } catch {
      /* as above */
    }
    await afterMutating(set, get);
  },
  // Signing out. The notice counter is not reset: it only ever has to keep
  // moving for a consumer to notice, and restarting it at zero after a read
  // that was already at zero would hide the next change.
  reset: () => set({ lists: NO_FRIENDS, loaded: false, pending: null }),
}));
