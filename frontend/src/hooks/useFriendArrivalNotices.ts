import { useEffect, useRef } from "react";

import { announcedFriendships } from "../lib/friendsApi";
import { useFriendsStore } from "../store/friendsStore";
import { useToast } from "../lib/toast";
import { useOpenOverlay } from "./useOverlayRoute";
import { FRIENDS_PATH } from "../lib/overlayRoutes";
import type { FriendEntry } from "../lib/friends";
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
canvas is worse than the news is good. */

/** Long enough to notice, read, and reach the button, mid-turn.

Not indefinite: it is still a toast, and something that never leaves on its
own is a notice, which this deliberately is not. */
const ACTIONABLE_MS = 12000;
export function useFriendArrivalNotices(): void {
  const notices = useFriendsStore((state) => state.notices);
  const accept = useFriendsStore((state) => state.accept);
  const { notify } = useToast();
  const openOverlay = useOpenOverlay();
  // The seq this has already spoken about. A ref rather than state: reacting
  // to it must not itself cause a render, and the store's counter is the only
  // thing that decides whether there is anything to say.
  const spoken = useRef(notices.seq);

  useEffect(() => {
    if (notices.seq === spoken.current) return;
    spoken.current = notices.seq;

    const { arrived, accepted } = notices;
    if (arrived.length === 1) {
      const asker = arrived[0];
      notify(ui.useFriendArrivalNotices.wantsToBeFriends({ name: asker.displayName }), ui.useFriendArrivalNotices.info, ACTIONABLE_MS, {
        label: "Accept",
        onClick: () => void accept(asker.userId),
      });
    } else if (arrived.length > 1) {
      notify(manyArrived(arrived), ui.useFriendArrivalNotices.info, ACTIONABLE_MS, {
        label: "Open",
        onClick: () => openOverlay(FRIENDS_PATH),
      });
    }

    // Nothing to do about an acceptance - it is already a friendship - so
    // this one is only read, and keeps the ordinary length.
    if (accepted.length === 1) {
      notify(ui.useFriendArrivalNotices.acceptedYourRequest({ name: accepted[0].displayName }));
    } else if (accepted.length > 1) {
      notify(ui.useFriendArrivalNotices.severalAccepted({ count: accepted.length }));
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
  }, [notices, notify, accept, openOverlay]);
}

function manyArrived(arrived: FriendEntry[]): string {
  const others = arrived.length - 1;
  return `${arrived[0].displayName} and ${others} other${others > 1 ? "s" : ""} want to be friends.`;
}
