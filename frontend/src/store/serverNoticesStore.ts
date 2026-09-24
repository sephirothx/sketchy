import { create } from "zustand";

import type { ConnectionStatus } from "../lib/connectionStatus.ts";
import type { ServerShutdownNotice } from "../types.ts";

/** What the server and the connection have said about this tab, in one place.

It lived in `App`'s local state and in the connection banner's, which was fine
while a banner at the top of the page was the only thing that showed it. The
room header shows two of these as chips now (#797), so the facts are shared and
each surface decides for itself how to say them. Written only by
`useServerNotices`; everything else reads. */
export type RoomEndReason = "server-update" | "room-closed" | "kicked";

interface ServerNoticesStore {
  shutdownNotice: ServerShutdownNotice | null;
  paused: boolean;
  restarted: boolean;
  serverFull: string | null;
  updateRequired: boolean;
  connection: ConnectionStatus;
  /** The connection has been in trouble for long enough to pause the room's stage. */
  pauseDue: boolean;
  /** The connection dropped while a planned-deploy drain was on screen. */
  lostDuringDrain: boolean;
  /** The room this tab was in no longer exists, and why (#823). Keyed by code, so
   *  it describes that room only and never the next one. */
  roomEnded: { code: string; reason: RoomEndReason } | null;
  /** The drain (its `startedAt`) whose opening card this tab already showed (#826). */
  drainCueSeenFor: string | null;
  set: (partial: Partial<Omit<ServerNoticesStore, "set" | "markRoomEnded" | "markKickedFromRoom">>) => void;
  /** Record that rejoining *code* was refused because the room is gone. */
  markRoomEnded: (code: string) => void;
  /** Record that rejoining *code* was refused because a vote removed this
   *  player while the tab was away (#1010): final for that room, like an
   *  ending, rather than a failure to retry on every reconnect. */
  markKickedFromRoom: (code: string) => void;
}

export const useServerNoticesStore = create<ServerNoticesStore>((set) => ({
  shutdownNotice: null,
  paused: false,
  restarted: false,
  serverFull: null,
  updateRequired: false,
  connection: "connected",
  pauseDue: false,
  lostDuringDrain: false,
  roomEnded: null,
  drainCueSeenFor: null,
  set: (partial) => set(partial),
  // A drain seen before the loss is what makes this an update rather than a
  // room that simply closed: rooms are process-owned (one worker, no
  // snapshots), so a server that went away after draining took the room with
  // it. The end screen says so, which is why the "server was updated" banner
  // is spent here rather than shown on top of it.
  //
  // The first answer for a room stands: by the next refusal the flags that
  // named the reason have been spent, and asking again would relabel an update
  // as a room that merely closed.
  markRoomEnded: (code) =>
    set((state) => state.roomEnded?.code === code ? state : ({
      roomEnded: {
        code,
        reason: state.lostDuringDrain || state.restarted ? "server-update" : "room-closed",
      },
      restarted: false,
      lostDuringDrain: false,
    })),
  // Told apart from an ending: the room is still there, and the sentence
  // has to say why this player is not. It overrides an earlier answer for
  // the same code, since the kick is the more specific of the two.
  markKickedFromRoom: (code) => set({ roomEnded: { code, reason: "kicked" } }),
}));
