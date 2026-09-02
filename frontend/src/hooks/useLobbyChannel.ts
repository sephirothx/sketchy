import { useEffect } from "react";

import { resubscribeDelayMs } from "../lib/lobbyChannel";
import { emitWithAck, socket } from "../lib/socket";
import { usePresenceStore } from "../store/presenceStore";
import { useRoomsStore } from "../store/roomsStore";

/** Subscribe to the lobby channel for as long as it is on screen.

Two feeds ride it — who is online, and the public room list — each with its own
revision, because they move independently. One subscription carries both, and
one acknowledgement hands over both baselines, so there is never a window in
which this client is applying changes to a list it has not been given.

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
    // Bumped whenever the socket changes identity. An acknowledgement that
    // arrives after that describes a sequence which no longer exists, and
    // applying it would stamp the client into a numbering the server has
    // forgotten.
    let generation = 0;
    let asking = false;
    // Whether an acknowledgement has landed on *this* connection. The server
    // joins the channel before it builds the answer, so a delta can arrive
    // first, and there is nothing sensible to apply it to yet.
    let baseline = false;
    let attempt = 0;
    let retry: number | null = null;

    function stopRetrying() {
      if (retry === null) return;
      window.clearTimeout(retry);
      retry = null;
    }

    async function subscribe(): Promise<void> {
      // One in flight at a time. Every delta that finds the store out of step
      // asks for a resync, and while the answer is on its way each further
      // delta finds it out of step again - so without this a single missed
      // message turns into one subscription per tick.
      if (cancelled || asking || !socket.connected) return;
      stopRetrying();
      asking = true;
      const mine = generation;
      try {
        const answer = await emitWithAck<Record<string, unknown>>("watch_lobby", {});
        if (cancelled || mine !== generation) return;
        if (!answer?.ok) throw new Error("watch_lobby was refused");
        usePresenceStore.getState().receiveSnapshot(answer);
        useRoomsStore.getState().receiveSnapshot(answer.rooms, answer.roomsRevision);
        baseline = true;
        attempt = 0;
      } catch {
        // Nothing else will ask. A disconnect is answered by `onConnect`, but
        // a refusal or a timed-out acknowledgement on a socket that stays up
        // would otherwise leave this lobby loading for ever: the room list has
        // no other source now, and a quiet server sends no delta to notice a
        // gap with.
        if (cancelled || mine !== generation || !socket.connected) return;
        attempt += 1;
        retry = window.setTimeout(() => {
          retry = null;
          void subscribe();
        }, resubscribeDelayMs(attempt));
      } finally {
        if (mine === generation) asking = false;
      }
    }

    const onPresence = (payload: unknown) => {
      if (cancelled || !baseline) return;
      usePresenceStore.getState().receiveDelta(payload);
      // A delta that did not follow the one we hold means something was
      // missed. The store is not patched around the gap - it is replaced.
      if (usePresenceStore.getState().presence.needsResync) void subscribe();
    };

    const onRooms = (payload: unknown) => {
      if (cancelled || !baseline) return;
      useRoomsStore.getState().receiveDelta(payload);
      if (useRoomsStore.getState().rooms.needsResync) void subscribe();
    };

    // A reconnect is a new socket in a new server, so whatever revisions these
    // stores held belong to sequences that no longer exist.
    const onConnect = () => {
      generation += 1;
      asking = false;
      baseline = false;
      attempt = 0;
      stopRetrying();
      usePresenceStore.getState().reset();
      useRoomsStore.getState().markStale();
      void subscribe();
    };
    // Presence empties and the room list only goes stale - see `markRoomsStale`
    // for why the two lists answer a dropped socket differently.
    const onDisconnect = () => {
      generation += 1;
      asking = false;
      baseline = false;
      stopRetrying();
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
      stopRetrying();
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
