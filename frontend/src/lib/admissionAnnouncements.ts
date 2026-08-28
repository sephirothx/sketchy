/** What the server has announced about admission, and on which connection.

Split out of the hook so the transitions can be tested. They are three lines
each, and one of them was still wrong after review: a drain announcement that
outlived its connection left an operations page reporting that the *replacement*
server was draining, with no fresh snapshot able to correct it, because the
merge ORs the two. A live check caught that; nothing in CI would have. */

export interface AdmissionAnnouncements {
  /** Announced by this connection. Within one, a drain is one-way. */
  draining: boolean;
  /** Null when nothing has been said, so a reader defers to what it fetched. */
  paused: boolean | null;
  /** Bumped on every (re)connect; anything fetched before it is from a
      process that is gone. */
  connection: number;
}

export const NO_ANNOUNCEMENTS: AdmissionAnnouncements = {
  draining: false,
  paused: null,
  connection: 0,
};

export type AdmissionEvent =
  | { type: "connect" }
  | { type: "disconnect" }
  | { type: "draining" }
  | { type: "paused"; paused: boolean };

/** Fold one announcement into what is known.

An announcement describes the process that made it, and a drain is precisely
the thing that ends one — so it must not survive into the next connection,
where it would be the old server's last words about the new one.

**The clearing happens on `disconnect`, not on `connect`, and that ordering is
load-bearing.** A server that is paused or draining says so from inside its
connection handler, before the namespace acknowledgement; socket.io-client
buffers those events and, in `onconnect`, flushes them *and then* emits
`connect` (`onevent` → `receiveBuffer`, `onconnect` → `emitBuffered()` →
`emitReserved("connect")`). Resetting on `connect` therefore erases the
authoritative state the new server had just sent. Resetting when the previous
connection ends leaves nothing to erase.

`connect` still counts the connection, because a snapshot fetched over the old
one describes a process that is gone. */
export function announcementsAfter(
  state: AdmissionAnnouncements,
  event: AdmissionEvent,
): AdmissionAnnouncements {
  switch (event.type) {
    case "disconnect":
      return { ...state, draining: false, paused: null };
    case "connect":
      return { ...state, connection: state.connection + 1 };
    case "draining":
      return { ...state, draining: true };
    case "paused":
      return { ...state, paused: event.paused };
  }
}
