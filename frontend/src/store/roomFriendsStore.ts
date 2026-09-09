import { create } from "zustand";

import { emitWithAck } from "../lib/socket";

/** Which seats in the room this socket is in belong to friends.

Seats, not accounts: R-ROOM-07 keeps account ids out of everything a room
hands a client, so the server resolves the friendship and answers with the
seat ids the client can already see.

Held apart from `friendsStore`, which is about the account's own lists and
outlives any room. This is scoped to one seating and is emptied on the way
out, so a stale mark cannot survive into the next room — where the same seat
id would mean somebody else entirely.

Asked for rather than pushed. The answer changes on two unrelated events — the
roster moving, and the account's friendships moving — and one command the
client re-issues on either is simpler than a second broadcast that would have
to be addressed to one socket anyway, since every reader's answer differs. */
interface RoomFriendsStore {
  /** Seat ids, as a set: every row asks about itself while rendering. */
  seatIds: Set<string>;
  refresh: () => Promise<void>;
  reset: () => void;
}

/** Ordering, so a slow answer cannot repaint a roster that has moved on.

Two things trigger a read - the roster changing and `friends_changed` - and
leaving a room cancels the question outright. All three can overlap, and the
answer names seats, which only mean anything in the room they were asked
about: an answer from the previous room would mark whoever now holds those
ids. So a read applies only if nothing newer has been issued since. Unlike
the account's own lists, there is no baseline to preserve here - the set is
either current or wrong - so the newest issued wins outright. */
let readSeq = 0;

export const useRoomFriendsStore = create<RoomFriendsStore>((set) => ({
  seatIds: new Set(),
  refresh: async () => {
    const seq = ++readSeq;
    try {
      const answer = await emitWithAck<{ ok?: boolean; playerIds?: unknown }>(
        "friends_in_room",
        {},
      );
      if (seq !== readSeq) return;
      const ids = Array.isArray(answer?.playerIds) ? answer.playerIds : [];
      set({
        seatIds: new Set(ids.filter((id): id is string => typeof id === "string")),
      });
    } catch {
      // A mark that does not arrive is a mark that is not drawn. Nothing here
      // is load-bearing, so a failure leaves the roster reading exactly as it
      // did before friendships were drawn on it at all.
      if (seq !== readSeq) return;
      set({ seatIds: new Set() });
    }
  },
  reset: () => {
    // Anything in flight is now about a room this client has left.
    readSeq += 1;
    set({ seatIds: new Set() });
  },
}));
