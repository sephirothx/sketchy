import { create } from "zustand";

import { withArrivals, type FriendEntry } from "../lib/friends.ts";

/**
 * The friend requests the room bar is showing as a chip.
 *
 * Outside a room a request arriving is a toast with *Accept* (R-FRIEND-12).
 * In one, a toast lands on the phone's chat feed and the desktop drawer's
 * palette, so there it is a chip in the room bar beside a friend's
 * **Invitation**, which moved there for the same reason (R-UX-07, #1176,
 * #1197). The toast needs nothing kept - it says what arrived and goes - but
 * the chip stays until it is answered or put off, so what it names lives here.
 *
 * Only what the notice *named*: whether each is still waiting is read off the
 * friends lists at the moment it is drawn (`stillWaiting`), so an answer given
 * anywhere - the friends surface, another tab, the asker withdrawing - takes
 * it down without this store having to hear about it.
 */
interface FriendRequestNoticeStore {
  askers: FriendEntry[];
  /** What the app-level region says about them: the sentence for the ones
      that arrived while a room was up, said once as they land, and nothing
      for a toast's that moved in - the toast already said it. */
  announcement: string;
  /** Requests that arrived, or a toast's that moved into the bar. */
  show: (arrived: FriendEntry[], announcement?: string) => void;
  /** Narrowed to the ones still waiting, when some were answered or withdrawn.
      The words go too: they named who arrived, and the next arrival - the
      same person asking again included - is said afresh. */
  keep: (waiting: FriendEntry[]) => void;
  /** Answered, put off with *Not now*, or the room left. Sends nothing. */
  clear: () => void;
}

export const useFriendRequestNoticeStore = create<FriendRequestNoticeStore>((set) => ({
  askers: [],
  announcement: "",
  show: (arrived, announcement) =>
    set((state) => ({
      askers: withArrivals(state.askers, arrived),
      announcement: announcement ?? state.announcement,
    })),
  keep: (waiting) => set({ askers: waiting, announcement: "" }),
  // The words go with the chip, so the next request is said afresh even when
  // its sentence is the same one.
  clear: () => set((state) => (state.askers.length === 0 && state.announcement === "" ? state : { askers: [], announcement: "" })),
}));
