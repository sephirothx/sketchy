import { useCallback, useEffect, useRef } from "react";

import { announcedFriendships } from "../lib/friendsApi";
import { useFriendsStore } from "../store/friendsStore";
import { useFriendInviteStore } from "../store/friendInviteStore";
import { useFriendRequestNoticeStore } from "../store/friendRequestNoticeStore";
import { useToast } from "../lib/toast";
import { useOpenOverlay } from "./useOverlayRoute";
import { FRIENDS_PATH } from "../lib/overlayRoutes";
import {
  friendRequestSentence,
  stillFriends,
  stillWaiting,
  withArrivals,
  type FriendEntry,
} from "../lib/friends";
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

An acceptance in a room is held instead, and said as the ordinary toast once
the room is left (#1200). It has nothing to offer - it is already a
friendship - so there is no chip for it to be, and a toast there stood on the
phone's newest chat line for its whole five seconds. Held rather than said
quietly: it is good news that keeps, and a game is exactly the moment not to
interrupt with it. Nothing is announced to a screen reader in the room
either, for the same reason. Several held are one toast, not a burst on the
way out; one that is no longer a friendship by then is dropped, because it is
read off the friends list when it is finally said; and it is recorded as told
only when it is (R-FRIEND-14), so a tab closed mid-game tells it on the next
visit. An acceptance toast still standing when a room opens is taken down and
held with the rest. Each tab holds its own, as each tab has always had its own
toasts.

Either way a request's notice goes the moment it stops being true. A request answered on the
friends surface, in another tab, or withdrawn by the person who asked leaves
`incoming` on the next read, and the toast or the chip naming it goes with it:
the toast's Accept used to stand for the rest of its twelve seconds offering
an answer that had already been given. */

/** Long enough to notice, read, and reach the button, mid-turn.

Not indefinite: it is still a toast, and something that never leaves on its
own is a notice, which this deliberately is not. */
const ACTIONABLE_MS = 12000;

/** How long an acceptance toast stands: `notify`'s default, since it is
    only read. Kept here so a toast still up when a room opens can be found. */
const READ_MS = 5000;

/** A toast on screen, and whom it named. */
interface NamedToast {
  id: number;
  named: FriendEntry[];
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
  const keepInBar = useFriendRequestNoticeStore((state) => state.keep);
  const announcement = useFriendRequestNoticeStore((state) => state.announcement);
  const { notify, dismiss } = useToast();
  const openOverlay = useOpenOverlay();
  // The seq this has already spoken about. A ref rather than state: reacting
  // to it must not itself cause a render, and the store's counter is the only
  // thing that decides whether there is anything to say.
  const spoken = useRef(notices.seq);
  const requestToasts = useRef<NamedToast[]>([]);
  const acceptedToasts = useRef<NamedToast[]>([]);
  // Acceptances that arrived while a room bar was up, waiting for the room
  // to be left (#1200).
  const held = useRef<FriendEntry[]>([]);

  // Say who accepted, then record them as told - after the notify, because a
  // record of telling that outlives the telling is the bug R-FRIEND-14 is
  // about, and only the ones this message named, so an acceptance that
  // landed since the read keeps its turn.
  const tellAccepted = useCallback(
    (accepted: FriendEntry[]) => {
      if (accepted.length === 0) return;
      const id = notify(
        accepted.length === 1
          ? ui.useFriendArrivalNotices.acceptedYourRequest({ name: accepted[0].displayName })
          : ui.useFriendArrivalNotices.severalAccepted({ count: accepted.length }),
        "info",
        READ_MS,
      );
      const now = Date.now();
      acceptedToasts.current = [
        ...acceptedToasts.current.filter((toast) => toast.until > now),
        { id, named: accepted, until: now + READ_MS },
      ];
      void announcedFriendships(accepted.map((entry) => entry.userId)).catch(() => {
        // Being thanked twice is the failure worth having here.
      });
    },
    [notify],
  );

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
      requestToasts.current.push({ id, named: arrived, until: Date.now() + ACTIONABLE_MS });
    }

    // Nothing to do about an acceptance - it is already a friendship - so
    // this one is only read, and keeps the ordinary length. In a room it
    // waits, unrecorded, so every read there names it again: kept once each.
    if (accepted.length > 0 && inRoomBar) {
      held.current = withArrivals(held.current, accepted);
    } else if (accepted.length > 0) {
      // Anything still held goes out with it, as one toast.
      const owed = withArrivals(stillFriends(held.current, useFriendsStore.getState().lists.friends), accepted);
      held.current = [];
      tellAccepted(owed);
    }
  }, [notices, notify, accept, openOverlay, inRoomBar, showInBar, tellAccepted]);

  // Answered anywhere: a toast goes as soon as anyone it named stops
  // waiting, since its words - "Ada and 2 others" - no longer hold and a toast
  // cannot be reworded; the Request badge keeps the count. The chip shrinks.
  useEffect(() => {
    const now = Date.now();
    requestToasts.current = requestToasts.current.filter((toast) => {
      if (toast.until <= now) return false;
      if (stillWaiting(toast.named, incoming).length === toast.named.length) return true;
      dismiss(toast.id);
      return false;
    });
  }, [incoming, dismiss]);
  useEffect(() => {
    // Every time it shrinks, not only when it empties: a request withdrawn
    // and asked again is a new arrival, so it must not still be on the chip -
    // or in the region's words, which would then not change and say nothing.
    const waiting = stillWaiting(inBar, incoming);
    if (waiting.length < inBar.length) keepInBar(waiting);
  }, [inBar, incoming, keepInBar]);

  // A room opening takes a request toast still standing into its bar, because
  // there the toast covers the chat; leaving puts the chip away. Not said
  // again on the way in - the toast already said it. An acceptance toast
  // still standing is taken down and held; leaving says what was held.
  useEffect(() => {
    if (!inRoomBar) {
      clearBar();
      const owed = stillFriends(held.current, useFriendsStore.getState().lists.friends);
      held.current = [];
      tellAccepted(owed);
      return;
    }
    const moving = requestToasts.current.filter((toast) => dismiss(toast.id));
    requestToasts.current = [];
    const waiting = stillWaiting(moving.flatMap((toast) => toast.named), useFriendsStore.getState().lists.incoming);
    if (waiting.length > 0) showInBar(waiting);
    const standing = acceptedToasts.current.filter((toast) => dismiss(toast.id));
    acceptedToasts.current = [];
    held.current = withArrivals(held.current, standing.flatMap((toast) => toast.named));
  }, [inRoomBar, dismiss, showInBar, clearBar, tellAccepted]);

  return announcement;
}
