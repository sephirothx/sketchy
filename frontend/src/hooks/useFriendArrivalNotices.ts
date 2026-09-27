import { useEffect, useRef } from "react";

import { announcedFriendships } from "../lib/friendsApi";
import { useFriendsStore } from "../store/friendsStore";
import { useFriendInviteStore } from "../store/friendInviteStore";
import { useFriendRequestNoticeStore } from "../store/friendRequestNoticeStore";
import { useToast } from "../lib/toast";
import { useOpenOverlay } from "./useOverlayRoute";
import { FRIENDS_PATH } from "../lib/overlayRoutes";
import { friendRequestSentence, stillWaiting, type FriendEntry } from "../lib/friends";
import { ui } from "../content/ui/index.ts";

/** Say when a friend request arrives, and when one is accepted.

Both were silent. `friends_changed` only ever caused a refetch, so somebody
who was not looking at the lobby's online panel learned nothing, and a request
they had sent being accepted was invisible from every screen.

A toast rather than a notice that stays: this reports something that has
already happened, and it will still be true after the turn ends. A notice that
had to be dismissed would interrupt a game to say so.

But it carries the answer people actually want. A request arriving offers
**Accept** right there, because the alternative is "go and find the menu, open
Friends, find the row" for the one answer that is almost always the intended
one. Declining is deliberately *not* offered: it is kept, so it cannot be
re-sent into (R-FRIEND-05), and a permanent refusal does not belong on a
control that disappears on a timer. It stays on the friends surface, behind
its confirmation, which the badge points at.

Several at once get **Open** instead of Accept: one button cannot mean four
different people, and the surface is where a list is answered.

Actionable toasts last longer than the default, because the default is sized
for something you only have to read, and this one has to be reached before it
goes. Names one person and counts the rest rather than firing one toast per
row: a game ending can settle several at once, and four stacked toasts over a
canvas is worse than the news is good.

In a room a request is not a toast at all but a chip in the room bar, beside a
friend's **Invitation** (`RoomNoticeChips`): the toast's spot there is the
phone's chat feed and the desktop drawer's palette (R-UX-07, #1197). The room
bar holds the invitation's claim while it is up, and the same claim says where
a request goes. A toast still standing when a room opens moves into the bar,
and the chip is put away when the room is left - the **Request badge** keeps
the count from there, which is what it is for.

Either way it goes the moment it stops being true. A request answered on the
friends surface, in another tab, or withdrawn by the person who asked leaves
`incoming` on the next read, and the toast or the chip naming it goes with it:
the toast's Accept used to stand for the rest of its twelve seconds offering
an answer that had already been given. */

/** Long enough to notice, read, and reach the button, mid-turn.

Not indefinite: it is still a toast, and something that never leaves on its
own is a notice, which this deliberately is not. */
const ACTIONABLE_MS = 12000;

/** A request toast on screen, and whom it named. */
interface RequestToast {
  id: number;
  askers: FriendEntry[];
  until: number;
}

/** Says the news, and returns what the app-level region should say for a
    request that went into the room bar - which says nothing itself, since the
    bar is not drawn while a phone's guess keyboard is up (#1176). */
export function useFriendArrivalNotices(): string {
  const notices = useFriendsStore((state) => state.notices);
  const incoming = useFriendsStore((state) => state.lists.incoming);
  const accept = useFriendsStore((state) => state.accept);
  const inRoomBar = useFriendInviteStore((state) => state.roomBarClaims > 0);
  const inBar = useFriendRequestNoticeStore((state) => state.askers);
  const showInBar = useFriendRequestNoticeStore((state) => state.show);
  const clearBar = useFriendRequestNoticeStore((state) => state.clear);
  const announcement = useFriendRequestNoticeStore((state) => state.announcement);
  const { notify, dismiss } = useToast();
  const openOverlay = useOpenOverlay();
  // The seq this has already spoken about. A ref rather than state: reacting
  // to it must not itself cause a render, and the store's counter is the only
  // thing that decides whether there is anything to say.
  const spoken = useRef(notices.seq);
  const requestToasts = useRef<RequestToast[]>([]);

  useEffect(() => {
    if (notices.seq === spoken.current) return;
    spoken.current = notices.seq;

    const { arrived, accepted } = notices;
    if (arrived.length > 0 && inRoomBar) {
      // Said once, here, when it lands; the chip carries it from then on.
      showInBar(arrived, friendRequestSentence(arrived));
    } else if (arrived.length > 0) {
      const id = notify(
        friendRequestSentence(arrived),
        "info",
        ACTIONABLE_MS,
        arrived.length === 1
          ? { label: ui.useFriendArrivalNotices.accept, onClick: () => void accept(arrived[0].userId) }
          : { label: ui.useFriendArrivalNotices.open, onClick: () => openOverlay(FRIENDS_PATH) },
      );
      requestToasts.current.push({ id, askers: arrived, until: Date.now() + ACTIONABLE_MS });
    }

    // Nothing to do about an acceptance - it is already a friendship - so
    // this one is only read, and keeps the ordinary length.
    if (accepted.length === 1) {
      notify(ui.useFriendArrivalNotices.acceptedYourRequest({ name: accepted[0].displayName }), "info");
    } else if (accepted.length > 1) {
      notify(ui.useFriendArrivalNotices.severalAccepted({ count: accepted.length }), "info");
    }
    // Told, so it is not told again - and only the ones this message named,
    // so an acceptance that landed since the read keeps its turn. After the
    // notify, because a record of telling that outlives the telling is the
    // bug this whole thing exists to fix (R-FRIEND-14).
    if (accepted.length > 0) {
      void announcedFriendships(accepted.map((entry) => entry.userId)).catch(
        () => {
          // Being thanked twice is the failure worth having here.
        },
      );
    }
  }, [notices, notify, accept, openOverlay, inRoomBar, showInBar]);

  // Answered anywhere: a toast goes once nobody it named is still waiting,
  // and so does the chip. A toast for several stays while any of them is,
  // because its Open still leads somewhere worth going.
  useEffect(() => {
    const now = Date.now();
    requestToasts.current = requestToasts.current.filter((toast) => {
      if (toast.until <= now) return false;
      if (stillWaiting(toast.askers, incoming).length > 0) return true;
      dismiss(toast.id);
      return false;
    });
  }, [incoming, dismiss]);
  useEffect(() => {
    if (inBar.length > 0 && stillWaiting(inBar, incoming).length === 0) clearBar();
  }, [inBar, incoming, clearBar]);

  // A room opening takes a request toast still standing into its bar, because
  // there the toast covers the chat; leaving puts the chip away. Not said
  // again on the way in - the toast already said it.
  useEffect(() => {
    if (!inRoomBar) {
      clearBar();
      return;
    }
    const moving = requestToasts.current.filter((toast) => dismiss(toast.id));
    requestToasts.current = [];
    const waiting = stillWaiting(moving.flatMap((toast) => toast.askers), useFriendsStore.getState().lists.incoming);
    if (waiting.length > 0) showInBar(waiting);
  }, [inRoomBar, dismiss, showInBar, clearBar]);

  return announcement;
}
