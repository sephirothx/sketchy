import { useEffect } from "react";

import { parseFriendsOnline } from "../lib/friendPresence";
import { emitWithAck, socket } from "../lib/socket";
import { useFriendsStore } from "../store/friendsStore";
import { useFriendPresenceStore } from "../store/friendPresenceStore";

/** Keep the online-friends map current, app-wide (#873, #878).

Asks `friends_online` whenever the socket connects or the set of friends
changes, and applies `friend_presence` pushes in between. Pushes are live and
have no backlog, so a reconnect asks again rather than trusting the map.

An account with no friends - a guest always - asks nothing: the answer could
only be empty, and the server pushes nothing to it either. */
export function useFriendPresence(): void {
  const replace = useFriendPresenceStore((state) => state.replace);
  const receive = useFriendPresenceStore((state) => state.receive);
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

  // Another account's friends are never shown to this one.
  useEffect(() => reset, [ownerId, reset]);

  useEffect(() => {
    if (!ownerId || !friendKey) return;
    let current = true;
    const ask = () => {
      void emitWithAck<unknown>("friends_online", {})
        .then((answer) => {
          if (current && (answer as { ok?: unknown } | null)?.ok === true) {
            replace(parseFriendsOnline(answer));
          }
        })
        .catch(() => {
          // The next connect asks again; pushes keep what is already known.
        });
    };
    socket.on("friend_presence", receive);
    socket.on("connect", ask);
    if (socket.connected) ask();
    return () => {
      current = false;
      socket.off("friend_presence", receive);
      socket.off("connect", ask);
    };
  }, [ownerId, friendKey, replace, receive]);
}
