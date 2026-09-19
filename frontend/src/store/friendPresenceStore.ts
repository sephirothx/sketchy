import { create } from "zustand";

import { NO_FRIENDS_ONLINE, type FriendPresenceMap } from "../lib/friendPresence";

interface FriendPresenceStore {
  online: FriendPresenceMap;
  /** Replace the map: every answer to `friends_online` is whole. */
  replace: (online: FriendPresenceMap) => void;
  reset: () => void;
}

export const useFriendPresenceStore = create<FriendPresenceStore>((set) => ({
  online: NO_FRIENDS_ONLINE,
  replace: (online) => set({ online }),
  reset: () => set({ online: NO_FRIENDS_ONLINE }),
}));
