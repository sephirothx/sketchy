import { useEffect } from "react";

import { emitWithAck, socket } from "../lib/socket";
import { usePresenceStore } from "../store/presenceStore";

/** Subscribe to the lobby's presence channel for as long as it is on screen.

Membership is asked for rather than derived from anything the server knows,
which is what bounds the broadcast to the lobbies actually open. Mounted by
the lobby page alone: a player inside a room is not watching this list, and
should not be paying for it mid-game. */
export function useLobbyPresence(): void {
  useEffect(() => {
    let cancelled = false;
    const store = usePresenceStore.getState();

    async function subscribe() {
      try {
        const answer = await emitWithAck<Record<string, unknown>>(
          "watch_lobby",
          {},
        );
        if (cancelled || !answer?.ok) return;
        store.receiveSnapshot(answer);
      } catch {
        // A lobby with no presence list is still a working lobby: the room
        // browser is the page's job and this is decoration beside it. The
        // next connect retries.
      }
    }

    const onDelta = (payload: unknown) => {
      if (cancelled) return;
      usePresenceStore.getState().receiveDelta(payload);
      // A delta that did not follow the one we hold means something was
      // missed. The store is not patched around the gap - it is replaced.
      if (usePresenceStore.getState().presence.needsResync) void subscribe();
    };

    // A reconnect is a new socket in a new server, so whatever revision this
    // store held belongs to a sequence that no longer exists.
    const onConnect = () => {
      usePresenceStore.getState().reset();
      void subscribe();
    };
    const onDisconnect = () => usePresenceStore.getState().reset();

    socket.on("lobby_presence_changed", onDelta);
    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    if (socket.connected) void subscribe();

    return () => {
      cancelled = true;
      socket.off("lobby_presence_changed", onDelta);
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      usePresenceStore.getState().reset();
      // Best effort: the server drops a closed socket from the channel by
      // itself, so this only matters for a client that stayed connected and
      // navigated into a room.
      if (socket.connected) socket.emit("unwatch_lobby", {});
    };
  }, []);
}
