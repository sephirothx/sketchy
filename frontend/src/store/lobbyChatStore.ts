import { create } from "zustand";

import {
  EMPTY_LOBBY_CHAT,
  applyChatBacklog,
  applyChatLine,
  type LobbyChatState,
} from "../lib/lobbyChat";

interface LobbyChatStore {
  chat: LobbyChatState;
  /** Take the backlog from a `watch_lobby` answer; `replace` on a new socket. */
  receiveBacklog: (payload: unknown, replace: boolean) => void;
  /** Append one line the channel delivered, unless it is one we hold. */
  receiveLine: (payload: unknown) => void;
  /** Back to nothing, on leaving the lobby. Not on losing the socket: the
  lines are history, and stay drawn until a new answer replaces them. */
  reset: () => void;
}

export const useLobbyChatStore = create<LobbyChatStore>((set) => ({
  chat: EMPTY_LOBBY_CHAT,
  receiveBacklog: (payload, replace) =>
    set((state) => {
      const next = applyChatBacklog(state.chat, payload, replace);
      return next === state.chat ? state : { chat: next };
    }),
  // `applyChatLine` returns the state it was given for a duplicate or an
  // unreadable line, so an identical reference here is what keeps the panel
  // from re-rendering for a line it already shows.
  receiveLine: (payload) =>
    set((state) => {
      const next = applyChatLine(state.chat, payload);
      return next === state.chat ? state : { chat: next };
    }),
  reset: () => set({ chat: EMPTY_LOBBY_CHAT }),
}));
