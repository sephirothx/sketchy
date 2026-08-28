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
  | { type: "draining" }
  | { type: "paused"; paused: boolean };

/** Fold one announcement into what is known.

A `connect` resets everything the previous process said. That is the whole
point of tracking the connection: an announcement describes the process that
made it, and a drain is precisely the thing that ends one — so carrying it
across a reconnect would be the old server's last words about the new one. A
server that is paused or draining says so at the handshake, so the true state
arrives immediately behind the reset rather than being lost to it. */
export function announcementsAfter(
  state: AdmissionAnnouncements,
  event: AdmissionEvent,
): AdmissionAnnouncements {
  switch (event.type) {
    case "connect":
      return {
        draining: false,
        paused: null,
        connection: state.connection + 1,
      };
    case "draining":
      return { ...state, draining: true };
    case "paused":
      return { ...state, paused: event.paused };
  }
}
