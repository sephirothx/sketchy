import { create } from "zustand";

import type { ConnectionStatus } from "../lib/connectionStatus.ts";
import type { ServerShutdownNotice } from "../types.ts";

/** What the server and the connection have said about this tab, in one place.

It lived in `App`'s local state and in the connection banner's, which was fine
while a banner at the top of the page was the only thing that showed it. The
room header shows two of these as chips now (#797), so the facts are shared and
each surface decides for itself how to say them. Written only by
`useServerNotices`; everything else reads. */
interface ServerNoticesStore {
  shutdownNotice: ServerShutdownNotice | null;
  paused: boolean;
  restarted: boolean;
  serverFull: string | null;
  updateRequired: boolean;
  connection: ConnectionStatus;
  set: (partial: Partial<Omit<ServerNoticesStore, "set">>) => void;
}

export const useServerNoticesStore = create<ServerNoticesStore>((set) => ({
  shutdownNotice: null,
  paused: false,
  restarted: false,
  serverFull: null,
  updateRequired: false,
  connection: "connected",
  set: (partial) => set(partial),
}));
