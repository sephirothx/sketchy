import { useEffect, useRef } from "react";

import { useFriendsStore } from "../store/friendsStore";
import { useToast } from "../lib/toast";

/** Say when a friend request arrives, and when one is accepted.

Both were silent. `friends_changed` only ever caused a refetch, so somebody
who was not looking at the lobby's online panel learned nothing, and a request
they had sent being accepted was invisible from every screen.

A toast rather than a notice that stays: this reports something that has
already happened, and the thing to do about it is on the friends surface,
which the badge points at. A notice that had to be dismissed would interrupt a
turn to tell somebody a fact that will still be true afterwards.

Names one person and counts the rest, rather than one toast per row: a game
ending can settle several at once, and four stacked toasts over a canvas is
worse than the news is good. */
export function useFriendArrivalNotices(): void {
  const notices = useFriendsStore((state) => state.notices);
  const { notify } = useToast();
  // The seq this has already spoken about. A ref rather than state: reacting
  // to it must not itself cause a render, and the store's counter is the only
  // thing that decides whether there is anything to say.
  const spoken = useRef(notices.seq);

  useEffect(() => {
    if (notices.seq === spoken.current) return;
    spoken.current = notices.seq;
    for (const message of noticeLines(notices)) notify(message);
  }, [notices, notify]);
}

function noticeLines({
  arrived,
  accepted,
}: {
  arrived: { displayName: string }[];
  accepted: { displayName: string }[];
}): string[] {
  const lines: string[] = [];
  if (arrived.length === 1) {
    lines.push(`${arrived[0].displayName} wants to be friends.`);
  } else if (arrived.length > 1) {
    lines.push(
      `${arrived[0].displayName} and ${arrived.length - 1} other${arrived.length > 2 ? "s" : ""} want to be friends.`,
    );
  }
  if (accepted.length === 1) {
    lines.push(`${accepted[0].displayName} accepted your friend request.`);
  } else if (accepted.length > 1) {
    lines.push(`${accepted.length} people accepted your friend requests.`);
  }
  return lines;
}
