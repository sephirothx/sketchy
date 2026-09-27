import { create } from "zustand";

import type { FriendInvite } from "../lib/friends";

/**
 * The friend's invitation waiting for an answer, and where it is drawn.
 *
 * One invitation at a time, as there always was: a newer one replaces the
 * older. It lives here rather than in the component that hears it because it
 * has two homes (R-UX-07). Outside a room it is the floating card
 * (`FriendInviteNotice`); inside one it is a chip in the room bar
 * (`RoomNoticeChips`), because the card's bottom-centre spot is the phone
 * room's chat feed and the desktop drawer's palette, and a notice may not
 * cover either. The room bar says it is there by holding a claim; the card
 * steps aside while any claim is held.
 *
 * Join from either home takes the player out of the room they are in, so the
 * room says how it is left (#1198): the way its own Leave leaves it, asking
 * first whenever Leave would ask. It holds that here, because neither home is
 * inside the room - the card is drawn above every page.
 *
 * The same claim decides where a **Friend request** goes (#1197): while one is
 * held, a request arriving is the bar's chip rather than a toast
 * (`useFriendArrivalNotices`, `friendRequestNoticeStore`), for the same reason
 * - the toast stood on the same two spots. A claim is the one fact both
 * notices need, "a room bar is up", so it is kept once, here.
 */

/** Leave the room for this invitation - or ask first, and only on a yes.
`begin` takes the entry lock and spends the invitation, and hands back what
enters the friend's room once this one is left; null when another entry holds
the lock, and then the room stays where it is. */
export type RoomExit = (invite: FriendInvite, begin: () => (() => void) | null) => void;

interface FriendInviteStore {
  invite: FriendInvite | null;
  /** How many room bars are up. At zero the invitation is the card and a
      friend request a toast; above it, both are chips in the bar. */
  roomBarClaims: number;
  receive: (invite: FriendInvite) => void;
  /** Answered, dismissed or expired: nothing is left to draw. */
  clear: () => void;
  /** The room bar takes the invitation; the returned function gives it back. */
  claimRoomBar: () => () => void;
  /** How the room this tab sits in is left for an invitation; null outside one. */
  roomExit: RoomExit | null;
  /** The room says how it is left; the returned function takes that back. */
  holdRoomExit: (exit: RoomExit) => () => void;
}

export const useFriendInviteStore = create<FriendInviteStore>((set, get) => ({
  invite: null,
  roomBarClaims: 0,
  roomExit: null,
  receive: (invite) => set({ invite }),
  clear: () => set({ invite: null }),
  claimRoomBar: () => {
    set((state) => ({ roomBarClaims: state.roomBarClaims + 1 }));
    let released = false;
    return () => {
      // Released once: a cleanup that ran twice would hand the card back
      // while another bar still holds its claim.
      if (released) return;
      released = true;
      set((state) => ({ roomBarClaims: Math.max(0, state.roomBarClaims - 1) }));
    };
  },
  holdRoomExit: (exit) => {
    set({ roomExit: exit });
    return () => {
      // Only its own: a room that mounted in its place holds the newer one.
      if (get().roomExit === exit) set({ roomExit: null });
    };
  },
}));
