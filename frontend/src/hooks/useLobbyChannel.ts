import { useEffect } from "react";

import { emitWithAck, socket } from "../lib/socket";
import { usePresenceStore } from "../store/presenceStore";
import { useRoomsStore } from "../store/roomsStore";

/** Subscribe to the lobby channel for as long as it is on screen.

Two feeds ride it — who is online, and the public room list — each with its own
revision, because they move independently. One subscription carries both, and
one acknowledgement hands over both baselines, so there is never a window in
which this client is receiving changes to a list it has not been given.

Membership is asked for rather than derived from anything the server knows,
which is what bounds the broadcast to the clients actually showing it.

Mounted in two places, and not in a third. The lobby shows both lists; the
*waiting* room needs presence to offer an invitation to a friend who is around,
and pays for the room feed it does not read — a few hundred bytes a change,
against a second subscription to keep in step. Nowhere else: a player mid-game
is not reading any of this. */
export function useLobbyChannel(): void {
  useEffect(() => {
    let cancelled = false;

    async function subscribe() {
      try {
        const answer = await emitWithAck<Record<string, unknown>>("watch_lobby", {});
        if (cancelled || !answer?.ok) return;
        usePresenceStore.getState().receiveSnapshot(answer);
        useRoomsStore.getState().receiveSnapshot(answer.rooms, answer.roomsRevision);
      } catch {
        // The next connect retries. Until then the lobby draws what it has,
        // which on a first load is its loading state.
      }
    }

    const onPresence = (payload: unknown) => {
      if (cancelled) return;
      usePresenceStore.getState().receiveDelta(payload);
      // A delta that did not follow the one we hold means something was
      // missed. The store is not patched around the gap - it is replaced.
      if (usePresenceStore.getState().presence.needsResync) void subscribe();
    };

    const onRooms = (payload: unknown) => {
      if (cancelled) return;
      useRoomsStore.getState().receiveDelta(payload);
      if (useRoomsStore.getState().rooms.needsResync) void subscribe();
    };

    // A reconnect is a new socket in a new server, so whatever revisions these
    // stores held belong to sequences that no longer exist.
    const onConnect = () => {
      usePresenceStore.getState().reset();
      useRoomsStore.getState().markStale();
      void subscribe();
    };
    // Presence empties and the room list only goes stale - see `markRoomsStale`
    // for why the two lists answer a dropped socket differently.
    const onDisconnect = () => {
      usePresenceStore.getState().reset();
      useRoomsStore.getState().markStale();
    };

    socket.on("lobby_presence_changed", onPresence);
    socket.on("lobby_rooms_changed", onRooms);
    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    if (socket.connected) void subscribe();

    return () => {
      cancelled = true;
      socket.off("lobby_presence_changed", onPresence);
      socket.off("lobby_rooms_changed", onRooms);
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      usePresenceStore.getState().reset();
      useRoomsStore.getState().reset();
      // Best effort: the server drops a closed socket from the channel by
      // itself, so this only matters for a client that stayed connected and
      // navigated into a room.
      if (socket.connected) socket.emit("unwatch_lobby", {});
    };
  }, []);
}
