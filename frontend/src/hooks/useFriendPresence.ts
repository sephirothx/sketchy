import { useEffect } from "react";

import { FRIENDS_POLL_MS, parseFriendsOnline } from "../lib/friendPresence";
import { emitWithAck, socket } from "../lib/socket";
import { useFriendsStore } from "../store/friendsStore";
import { useFriendPresenceStore } from "../store/friendPresenceStore";

/** Keep the online-friends map current while a surface that shows it is up
(#873, #878).

Polled rather than pushed (R-PRESENCE-06): asked on mount, on every connect,
whenever the set of friends changes, on the tab becoming visible, and every
`FRIENDS_POLL_MS` while it stays visible. Each answer replaces the map. A
stale row costs little - an invitation is checked by the server when it is
sent - and a push stream merged with these answers cost more than it bought.

The map is emptied on unmount and on disconnect: who is reachable is unknown
until the next answer, and a map left behind would show one surface's old
answer on the next. An account with no friends - a guest always - asks
nothing, since the answer could only be empty. */
export function useFriendPresence(): void {
  const replace = useFriendPresenceStore((state) => state.replace);
  const reset = useFriendPresenceStore((state) => state.reset);
  const ownerId = useFriendsStore((state) => state.ownerId);
  // Keyed on who the friends are, so a refetch that changed nothing does not
  // re-ask, and a friendship made or ended does.
  const friendKey = useFriendsStore((state) =>
    state.lists.friends
      .map((friend) => friend.userId)
      .sort()
      .join(","),
  );

  useEffect(() => {
    if (!ownerId || !friendKey) return reset;
    let current = true;
    // Bumped on every disconnect, so an answer from a connection that has
    // since closed never lands after the map was emptied for it.
    let connection = 0;
    const ask = () => {
      if (!socket.connected || document.visibilityState !== "visible") return;
      const askedOn = connection;
      void emitWithAck<unknown>("friends_online", {})
        .then((answer) => {
          // A refusal keeps the map: it says nothing about who is online.
          if (
            current &&
            askedOn === connection &&
            (answer as { ok?: unknown } | null)?.ok === true
          ) {
            replace(parseFriendsOnline(answer));
          }
        })
        .catch(() => {
          // The next poll asks again.
        });
    };
    const lost = () => {
      connection += 1;
      reset();
    };
    socket.on("connect", ask);
    socket.on("disconnect", lost);
    document.addEventListener("visibilitychange", ask);
    const timer = window.setInterval(ask, FRIENDS_POLL_MS);
    ask();
    return () => {
      current = false;
      window.clearInterval(timer);
      socket.off("connect", ask);
      socket.off("disconnect", lost);
      document.removeEventListener("visibilitychange", ask);
      reset();
    };
  }, [ownerId, friendKey, replace, reset]);
}
