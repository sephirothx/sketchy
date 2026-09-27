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
 */
interface FriendInviteStore {
  invite: FriendInvite | null;
  /** How many room bars are showing invitations; the card draws at zero. */
  roomBarClaims: number;
  receive: (invite: FriendInvite) => void;
  /** Answered, dismissed or expired: nothing is left to draw. */
  clear: () => void;
  /** The room bar takes the invitation; the returned function gives it back. */
  claimRoomBar: () => () => void;
}

export const useFriendInviteStore = create<FriendInviteStore>((set) => ({
  invite: null,
  roomBarClaims: 0,
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
}));
