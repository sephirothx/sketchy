import { useEffect, useRef, useState } from "react";

import {
  STAGE_PAUSE_DELAY_MS,
  connectionBannerDelayMs,
  resolveConnectionStatus,
  type ConnectionStatus,
} from "../lib/connectionStatus";
import { getRoomBindingStatus, subscribeRoomBinding } from "../lib/roomSessionBinding";
import {
  parsePausedNotice,
  parseShutdownNotice,
  shutdownSecondsRemaining,
} from "../lib/shutdownNotice";
import { hasEverConnected, onServerFull, socket } from "../lib/socket";
import { onUpdateRequired } from "../lib/updateRequired";
import { useGameStore } from "../store/gameStore";
import { useServerNoticesStore } from "../store/serverNoticesStore";
import { roomStage, type RoomStage } from "../lib/appNotices";

function currentConnection(): ConnectionStatus {
  return resolveConnectionStatus({
    online: typeof navigator === "undefined" || navigator.onLine,
    socketConnected: socket.connected,
    binding: getRoomBindingStatus(),
  });
}

// Never start on "reconnecting": on first render the socket has not connected
// yet by design, and showing the notice then would blame the network for an
// ordinary page load.
function initialConnection(): ConnectionStatus {
  const status = currentConnection();
  return status === "reconnecting" ? "connected" : status;
}

/** Feed the server-notice store from the socket, once, at the application root.

Where each notice is *shown* - a banner, a room chip, nowhere - is decided by
`placeNotices`; this only records what was said. */
export function useServerNotices() {
  const set = useServerNoticesStore((state) => state.set);
  // Whether a drain was on screen when the connection dropped, so the "we are
  // back" line can be shown once - after the notice itself has been cleared.
  const sawShutdownRef = useRef(false);

  useEffect(() => {
    const onServerShutdown = (payload: unknown) => {
      const notice = parseShutdownNotice(payload);
      if (!notice) return;
      set({ shutdownNotice: notice, restarted: false });
    };
    // Both notices describe the connection that carried them, and are dropped
    // when it ends rather than when the next one opens. A server that is
    // paused or draining says so at the handshake, and socket.io delivers
    // those buffered events *before* `connect` - so clearing there would erase
    // what the new server had just said. It also fixes the other direction: a
    // pause lifted while this client was away sends no notice on reconnect,
    // so a cached `true` would otherwise claim for ever that rooms are paused.
    const onDisconnect = () => {
      const draining = useServerNoticesStore.getState().shutdownNotice !== null;
      if (draining) sawShutdownRef.current = true;
      set({ shutdownNotice: null, paused: false, ...(draining ? { lostDuringDrain: true } : {}) });
    };
    // A player whose game vanished mid-round is owed the reason, so a drain
    // that ended in a restart is reported once the server is back - unless it
    // is back and *still* draining, which the handshake will have said just
    // above and which is not a "we are back" story.
    const onConnect = () => {
      if (!sawShutdownRef.current) return;
      sawShutdownRef.current = false;
      if (!useServerNoticesStore.getState().shutdownNotice) set({ restarted: true });
    };
    // A pause is not a version skew and not a drain: the server is still
    // here, so the notice clears when it is lifted rather than on a reload.
    const onServerPaused = (payload: unknown) => {
      const notice = parsePausedNotice(payload);
      if (notice) set({ paused: notice.paused });
    };
    socket.on("server_shutdown", onServerShutdown);
    socket.on("server_paused", onServerPaused);
    socket.on("disconnect", onDisconnect);
    socket.on("connect", onConnect);
    return () => {
      socket.off("server_shutdown", onServerShutdown);
      socket.off("server_paused", onServerPaused);
      socket.off("disconnect", onDisconnect);
      socket.off("connect", onConnect);
    };
  }, [set]);

  // Being turned away closes the socket immediately, so this is the only
  // chance to say why: without it the player sees a silent, permanent
  // disconnection and no reason for it.
  useEffect(() => onServerFull((reason) => set({ serverFull: reason })), [set]);
  // The tab is out of date and the one automatic reload did not fix it; the
  // socket is down for good and every command would be refused, so the only
  // thing left to offer is a reload the player chooses (#476).
  useEffect(() => onUpdateRequired(() => set({ updateRequired: true })), [set]);

  useEffect(() => {
    let pending: ReturnType<typeof setTimeout> | null = null;
    let pauseTimer: ReturnType<typeof setTimeout> | null = null;
    let shown = initialConnection();

    const clearPending = () => {
      if (pending === null) return;
      clearTimeout(pending);
      pending = null;
    };

    const commit = (next: ConnectionStatus) => {
      shown = next;
      if (next === "connected") {
        if (pauseTimer !== null) clearTimeout(pauseTimer);
        pauseTimer = null;
        set({ connection: next, pauseDue: false });
        return;
      }
      // A rebind that failed is not going to recover by waiting, so its card
      // is due at once; anything else waits out the pause delay.
      if (next === "failed") {
        set({ connection: next, pauseDue: true });
        return;
      }
      set({ connection: next });
      if (pauseTimer === null && !useServerNoticesStore.getState().pauseDue) {
        pauseTimer = setTimeout(() => {
          pauseTimer = null;
          if (shown !== "connected") set({ pauseDue: true });
        }, STAGE_PAUSE_DELAY_MS);
      }
    };
    commit(shown);

    const refresh = () => {
      const next = currentConnection();
      const delay = connectionBannerDelayMs(next, hasEverConnected());
      if (delay === 0) {
        clearPending();
        commit(next);
        return;
      }
      // Already showing it, or already counting down towards it.
      if (shown === next || pending !== null) return;
      pending = setTimeout(() => {
        pending = null;
        // Recompute on expiry: a connection can land without firing an event
        // that would have cancelled this, and a stale status must not show.
        commit(currentConnection());
      }, delay);
    };

    const unsubscribeBinding = subscribeRoomBinding(refresh);

    socket.on("connect", refresh);
    socket.on("disconnect", refresh);
    socket.on("connect_error", refresh);
    window.addEventListener("offline", refresh);
    window.addEventListener("online", refresh);
    refresh();
    return () => {
      clearPending();
      if (pauseTimer !== null) clearTimeout(pauseTimer);
      socket.off("connect", refresh);
      socket.off("disconnect", refresh);
      socket.off("connect_error", refresh);
      window.removeEventListener("offline", refresh);
      window.removeEventListener("online", refresh);
      unsubscribeBinding();
    };
  }, [set]);
}

/** Whole seconds left in the drain on screen, ticking; 0 when there is none. */
export function useDrainSecondsLeft(): number {
  const notice = useServerNoticesStore((state) => state.shutdownNotice);
  const [secondsLeft, setSecondsLeft] = useState(() =>
    notice ? shutdownSecondsRemaining(notice) : 0,
  );
  const [shownFor, setShownFor] = useState(notice);
  // A new notice restarts the count at once rather than a second later.
  if (shownFor !== notice) {
    setShownFor(notice);
    setSecondsLeft(notice ? shutdownSecondsRemaining(notice) : 0);
  }

  useEffect(() => {
    if (!notice) return;
    const timer = window.setInterval(() => setSecondsLeft(shutdownSecondsRemaining(notice)), 1000);
    return () => window.clearInterval(timer);
  }, [notice]);

  return secondsLeft;
}

/** The room's stage as `roomStage` decides it, for the room this tab is showing. */
export function useRoomStage(): RoomStage {
  const code = useGameStore((state) => state.code);
  const connection = useServerNoticesStore((state) => state.connection);
  const pauseDue = useServerNoticesStore((state) => state.pauseDue);
  const lostDuringDrain = useServerNoticesStore((state) => state.lostDuringDrain);
  const updateRequired = useServerNoticesStore((state) => state.updateRequired);
  const roomEnded = useServerNoticesStore((state) => state.roomEnded);
  return roomStage({ code, connection, pauseDue, lostDuringDrain, updateRequired, roomEnded });
}
