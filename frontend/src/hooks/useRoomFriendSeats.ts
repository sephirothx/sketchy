import { useEffect } from "react";

import { socket } from "../lib/socket";
import { useRoomFriendsStore } from "../store/roomFriendsStore";
import type { PlayerInfo } from "../types";

/** Keep the room's friend marks in step with the two things that move them.

The roster changes as people join and leave, and the account's friendships
change under `friends_changed` — and either can make a seat start or stop
being a friend's. Keyed on the seats present rather than on the array, so a
score update or a vote landing does not re-ask a question whose answer cannot
have changed.

Emptied on the way out, because seat ids are per-room: the same id in the next
room is somebody else, and a mark left behind would be drawn on them. */
export function useRoomFriendSeats(players: PlayerInfo[]): void {
  const refresh = useRoomFriendsStore((state) => state.refresh);
  const reset = useRoomFriendsStore((state) => state.reset);

  const seatKey = players
    .map((player) => player.playerId)
    .sort()
    .join(",");

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

  useEffect(() => () => reset(), [reset]);
}
