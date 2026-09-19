import { create } from "zustand";

import {
  NO_FRIENDS_ONLINE,
  applyFriendPresence,
  type FriendPresenceMap,
} from "../lib/friendPresence";

interface FriendPresenceStore {
  online: FriendPresenceMap;
  /** Replace the map: the answer to `friends_online`. */
  replace: (online: FriendPresenceMap) => void;
  /** Apply one `friend_presence` push. */
  receive: (payload: unknown) => void;
  reset: () => void;
}

export const useFriendPresenceStore = create<FriendPresenceStore>((set) => ({
  online: NO_FRIENDS_ONLINE,
  replace: (online) => set({ online }),
  receive: (payload) =>
    set((state) => {
      const next = applyFriendPresence(state.online, payload);
      return next === state.online ? state : { online: next };
    }),
  reset: () => set({ online: NO_FRIENDS_ONLINE }),
}));
