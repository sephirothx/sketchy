import { create } from "zustand";

import {
  NO_ROOMS,
  applyRoomsDelta,
  applyRoomsSnapshot,
  markRoomsStale,
  type RoomsState,
} from "../lib/lobbyRooms";

interface RoomsStore {
  rooms: RoomsState;
  receiveSnapshot: (rooms: unknown, revision: unknown) => void;
  receiveDelta: (payload: unknown) => void;
  markStale: () => void;
  reset: () => void;
}

export const useRoomsStore = create<RoomsStore>((set) => ({
  rooms: NO_ROOMS,
  receiveSnapshot: (rooms, revision) =>
    set({ rooms: applyRoomsSnapshot(rooms, revision) }),
  // An identical reference when there is nothing to do is what keeps the room
  // list from re-rendering on a tick that carried somebody else's news.
  receiveDelta: (payload) =>
    set((state) => {
      const next = applyRoomsDelta(state.rooms, payload);
      return next === state.rooms ? state : { rooms: next };
    }),
  markStale: () => set((state) => ({ rooms: markRoomsStale(state.rooms) })),
  reset: () => set({ rooms: NO_ROOMS }),
}));
