import { useEffect } from "react";

import { socket } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { subscribeRoomBinding } from "../lib/roomSessionBinding";
import { useRoomFriendsStore } from "../store/roomFriendsStore";

/** Keep the room's friend marks in step with the two things that move them.

The roster changes as people join and leave, and the account's friendships
change under `friends_changed` — and either can make a seat start or stop
being a friend's. Keyed on the seats present rather than on the array, so a
score update or a vote landing does not re-ask a question whose answer cannot
have changed.

Emptied on the way out, because seat ids are per-room: the same id in the next
room is somebody else, and a mark left behind would be drawn on them. */
export function useRoomFriendSeats(): void {
  const refresh = useRoomFriendsStore((state) => state.refresh);
  const reset = useRoomFriendsStore((state) => state.reset);
  // Read here rather than passed in: the one caller is whatever component
  // happens to live as long as the room, and making it carry a roster it does
  // not otherwise use would be a prop threaded through for this alone.
  const seatKey = useGameStore((state) =>
    state.players
      .map((player) => player.playerId)
      .sort()
      .join(","),
  );

  useEffect(() => {
    if (!seatKey) {
      reset();
      return;
    }
    void refresh();
  }, [seatKey, refresh, reset]);

  useEffect(() => {
    const onChanged = () => void refresh();
    socket.on("friends_changed", onChanged);
    return () => {
      socket.off("friends_changed", onChanged);
    };
  }, [refresh]);

  // And once the room has been rebound after a reconnect. `friends_changed`
  // is live and has no backlog, and a transport reconnect rebinds the same
  // room with the same seat ids - so the roster looks unchanged and the
  // effect above never re-runs, leaving marks that were made or removed while
  // the socket was down permanently wrong.
  //
  // Keyed on the binding reaching `ready` rather than on the socket's own
  // `connect`, which fires before `join_room` has been answered: asked then,
  // the server would resolve a socket that is not in the room yet and answer
  // that nobody here is a friend.
  useEffect(() => {
    return subscribeRoomBinding((status) => {
      if (status === "ready") void refresh();
    });
  }, [refresh]);

  useEffect(() => () => reset(), [reset]);
}
