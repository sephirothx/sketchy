import { useEffect, useRef, useState } from "react";
import { hasEverConnected, socket } from "../lib/socket";
import { getRoomBindingStatus, subscribeRoomBinding } from "../lib/roomSessionBinding";
import {
  connectionBannerDelayMs,
  resolveConnectionStatus,
  type ConnectionStatus,
} from "../lib/connectionStatus";

function currentStatus(): ConnectionStatus {
  return resolveConnectionStatus({
    online: typeof navigator === "undefined" || navigator.onLine,
    socketConnected: socket.connected,
    binding: getRoomBindingStatus(),
  });
}

// Never start on "reconnecting": on first render the socket has not connected
// yet by design, and showing the banner then would blame the network for an
// ordinary page load.
function initialStatus(): ConnectionStatus {
  const status = currentStatus();
  return status === "reconnecting" ? "connected" : status;
}

export function ConnectionStatusBanner() {
  const [status, setStatus] = useState<ConnectionStatus>(initialStatus);
  const shown = useRef(status);

  useEffect(() => {
    let pending: ReturnType<typeof setTimeout> | null = null;

    const clearPending = () => {
      if (pending === null) return;
      clearTimeout(pending);
      pending = null;
    };

    const commit = (next: ConnectionStatus) => {
      shown.current = next;
      setStatus(next);
    };

    const refresh = () => {
      const next = currentStatus();
      const delay = connectionBannerDelayMs(next, hasEverConnected());
      if (delay === 0) {
        clearPending();
        commit(next);
        return;
      }
      // Already showing it, or already counting down towards it.
      if (shown.current === next || pending !== null) return;
      pending = setTimeout(() => {
        pending = null;
        // Recompute on expiry: a connection can land without firing an event
        // that would have cancelled this, and a stale status must not show.
        commit(currentStatus());
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
      socket.off("connect", refresh);
      socket.off("disconnect", refresh);
      socket.off("connect_error", refresh);
      window.removeEventListener("offline", refresh);
      window.removeEventListener("online", refresh);
      unsubscribeBinding();
    };
  }, []);

  if (status === "connected") return null;
  return (
    <div className={`connection-status-banner ${status === "failed" ? "reconnecting" : status}`} role="status" aria-live="polite">
      {status === "offline"
        ? "You’re offline. Check your connection; Sketchy will reconnect automatically."
        : status === "failed"
          ? "Couldn’t restore your room session. Reload the page to rejoin."
          : "Connection lost — reconnecting…"}
    </div>
  );
}
