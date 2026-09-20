import { useEffect } from "react";

import { createHiddenWatch, resubscribeDelayMs } from "../lib/lobbyChannel";
import { createPendingDeltas } from "../lib/lobbyChannel";
import { chatResumeRequest } from "../lib/lobbyChat";
import { emitWithAck, socket } from "../lib/socket";
import { useAuthStore } from "../store/authStore";
import { useLobbyChatStore } from "../store/lobbyChatStore";
import { usePresenceStore } from "../store/presenceStore";
import { useRoomsStore } from "../store/roomsStore";

/** Subscribe to the lobby channel for as long as it is on screen.

Two feeds ride it — who is online, and the public room list — each with its own
revision, because they move independently. One subscription carries both, and
one acknowledgement hands over both baselines, so there is never a window in
which this client is applying changes to a list it has not been given.

The lobby's chat rides the same channel and the same acknowledgement, but it
is not a third feed: a line is an event, delivered the moment it is said, and
a gap in its numbering is expected rather than a reason to resync — a line is
deliberately not delivered to somebody who blocked its author. The
acknowledgement hands over the recent lines for the same reason it hands over
the other two baselines, so a line that beats it has something to be placed
against — and only the ones this client does not already hold, when it holds
lines from the same server process and account (#885).

Membership is asked for rather than derived from anything the server knows,
which is what bounds the broadcast to the clients actually showing it.

Mounted by the lobby alone. The waiting room used to mount it too, to offer an
invitation to a friend who was around; it now polls its own friends instead
(`useFriendPresence`, #873), and a player mid-game is not reading any of this. */
export function useLobbyChannel(): void {
  useEffect(() => {
    let cancelled = false;
    // Bumped whenever the socket changes identity. An acknowledgement that
    // arrives after that describes a sequence which no longer exists, and
    // applying it would stamp the client into a numbering the server has
    // forgotten.
    let generation = 0;
    let asking = false;
    // A resync decided while an acknowledgement is in flight - a replayed
    // delta that did not follow, the pending buffer overflowing - cannot be
    // issued from inside that attempt; it is remembered and issued the moment
    // the attempt settles, so it is never lost to the guard below.
    let wanted = false;
    // Whether an acknowledgement has landed on *this* connection. The server
    // joins the channel before it builds the answer, so a delta can arrive
    // first, and there is nothing sensible to apply it to yet.
    let baseline = false;
    // Deltas that arrive while the acknowledgement is pending are held, not
    // dropped, and replayed after the baseline if newer than it (#600). The
    // server joins the channel before its lookups, so a delta sent during
    // them does arrive here first; its baselines are read after, so such a
    // delta is never newer than them.
    const pending = createPendingDeltas();
    let attempt = 0;
    let retryAfterMs = 0;
    let retry: number | null = null;

    function stopRetrying() {
      if (retry === null) return;
      window.clearTimeout(retry);
      retry = null;
    }

    const hidden = createHiddenWatch({
      leave: () => {
        if (cancelled) return;
        baseline = false;
        pending.clear();
        stopRetrying();
        usePresenceStore.getState().reset();
        useRoomsStore.getState().markStale();
        if (socket.connected) socket.emit("unwatch_lobby", {});
      },
      rejoin: () => {
        if (!cancelled) void subscribe();
      },
      setTimeout: (handler, delayMs) => window.setTimeout(handler, delayMs),
      clearTimeout: (id) => window.clearTimeout(id),
    });
    const onVisibility = () => hidden.noteVisibility(document.visibilityState === "hidden");
    async function subscribe(): Promise<void> {
      // One in flight at a time. Every delta that finds the store out of step
      // asks for a resync, and while the answer is on its way each further
      // delta finds it out of step again - so without this a single missed
      // message turns into one subscription per tick.
      // Nothing re-subscribes a tab that has left the channel for being
      // hidden (#886) - a reconnect while it is away included; coming back
      // into view is what asks again.
      if (cancelled || !socket.connected || !hidden.watching) return;
      if (asking) {
        wanted = true;
        return;
      }
      // A retry already scheduled is the next ask, whatever wanted this one:
      // after a refusal it waits out the `retryAfterMs` the server named, and
      // asking sooner - a resync coalesced during the refused request, a gap
      // noticed meanwhile - would only be refused again (#885). A new socket
      // clears it first (`onConnect`), since its budget starts afresh.
      if (retry !== null) return;
      asking = true;
      wanted = false;
      const mine = generation;
      // Whether the backlog merges or replaces is the chat store's decision,
      // from the epoch and account (`applyChatBacklog`); this only says what
      // it holds, so the server can leave out the lines already here.
      const owner = useAuthStore.getState().user?.id ?? null;
      const chatHeld = chatResumeRequest(useLobbyChatStore.getState().chat, owner);
      try {
        const answer = await emitWithAck<Record<string, unknown>>("watch_lobby", chatHeld);
        if (cancelled || mine !== generation) return;
        if (!answer?.ok) {
          // The baseline has a budget of its own (#885); a refusal says when
          // to ask again, and asking sooner would only be refused again.
          if (typeof answer?.retryAfterMs === "number") retryAfterMs = answer.retryAfterMs;
          throw new Error("watch_lobby was refused");
        }
        usePresenceStore.getState().receiveSnapshot(answer);
        useRoomsStore.getState().receiveSnapshot(answer.rooms, answer.roomsRevision);
        useLobbyChatStore.getState().receiveBacklog(answer, owner);
        baseline = true;
        attempt = 0;
        const revisionOf = (value: unknown) => (typeof value === "number" ? value : 0);
        for (const held of pending.drain({
          presence: revisionOf(answer.revision),
          rooms: revisionOf(answer.roomsRevision),
          chatSeq: revisionOf(answer.chatSeq),
        })) {
          if (held.feed === "presence") usePresenceStore.getState().receiveDelta(held.payload);
          else if (held.feed === "rooms") useRoomsStore.getState().receiveDelta(held.payload);
          else useLobbyChatStore.getState().receiveLine(held.payload);
        }
        if (
          usePresenceStore.getState().presence.needsResync
          || useRoomsStore.getState().rooms.needsResync
        ) {
          void subscribe();
        }
      } catch {
        // Nothing else will ask. A disconnect is answered by `onConnect`, but
        // a refusal or a timed-out acknowledgement on a socket that stays up
        // would otherwise leave this lobby loading for ever: the room list has
        // no other source now, and a quiet server sends no delta to notice a
        // gap with.
        if (cancelled || mine !== generation || !socket.connected) return;
        attempt += 1;
        const delay = Math.max(resubscribeDelayMs(attempt), retryAfterMs);
        retryAfterMs = 0;
        retry = window.setTimeout(() => {
          retry = null;
          void subscribe();
        }, delay);
      } finally {
        if (mine === generation) {
          asking = false;
          if (wanted && !cancelled && socket.connected) {
            wanted = false;
            void subscribe();
          }
        }
      }
    }

    // A tab hidden for a while stops being a watcher (#886): it kept taking
    // every tick, room change and chat line while nobody was looking. It
    // leaves the channel after the grace and re-subscribes on return, which
    // costs one baseline - and only the chat it does not hold (#885).

    // Held while the baseline is pending; past the buffer's cap a fresh
    // baseline is asked for, since what was held no longer joins onto anything.
    const holdOrResubscribe = (feed: "presence" | "rooms" | "chat", payload: unknown) => {
      if (!pending.hold(feed, payload)) void subscribe();
    };

    const onPresence = (payload: unknown) => {
      if (cancelled) return;
      if (!baseline) {
        holdOrResubscribe("presence", payload);
        return;
      }
      usePresenceStore.getState().receiveDelta(payload);
      // A delta that did not follow the one we hold means something was
      // missed. The store is not patched around the gap - it is replaced.
      if (usePresenceStore.getState().presence.needsResync) void subscribe();
    };

    const onRooms = (payload: unknown) => {
      if (cancelled) return;
      if (!baseline) {
        holdOrResubscribe("rooms", payload);
        return;
      }
      useRoomsStore.getState().receiveDelta(payload);
      if (useRoomsStore.getState().rooms.needsResync) void subscribe();
    };

    // A line before the baseline is usually in the backlog the answer carries;
    // one said after the backlog was read is not, so it is held like the rest
    // and the store's sequence numbers drop the duplicates.
    const onChat = (payload: unknown) => {
      if (cancelled) return;
      if (!baseline) {
        holdOrResubscribe("chat", payload);
        return;
      }
      useLobbyChatStore.getState().receiveLine(payload);
    };

    // A reconnect is a new socket in a new server, so whatever revisions these
    // stores held belong to sequences that no longer exist.
    const onConnect = () => {
      generation += 1;
      asking = false;
      wanted = false;
      baseline = false;
      attempt = 0;
      pending.clear();
      stopRetrying();
      usePresenceStore.getState().reset();
      useRoomsStore.getState().markStale();
      void subscribe();
    };
    // Presence empties and the room list only goes stale - see `markRoomsStale`
    // for why the two lists answer a dropped socket differently. The chat is
    // left exactly as it is: those lines were said, and stay said.
    const onDisconnect = () => {
      generation += 1;
      asking = false;
      wanted = false;
      baseline = false;
      pending.clear();
      stopRetrying();
      usePresenceStore.getState().reset();
      useRoomsStore.getState().markStale();
    };

    socket.on("lobby_presence_changed", onPresence);
    socket.on("lobby_rooms_changed", onRooms);
    socket.on("lobby_chat_message", onChat);
    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    document.addEventListener("visibilitychange", onVisibility);
    if (socket.connected) void subscribe();

    return () => {
      cancelled = true;
      stopRetrying();
      pending.clear();
      socket.off("lobby_presence_changed", onPresence);
      socket.off("lobby_rooms_changed", onRooms);
      socket.off("lobby_chat_message", onChat);
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      document.removeEventListener("visibilitychange", onVisibility);
      hidden.stop();
      usePresenceStore.getState().reset();
      useRoomsStore.getState().reset();
      useLobbyChatStore.getState().reset();
      // Best effort: the server drops a closed socket from the channel by
      // itself, so this only matters for a client that stayed connected and
      // navigated into a room.
      if (socket.connected) socket.emit("unwatch_lobby", {});
    };
  }, []);
}
