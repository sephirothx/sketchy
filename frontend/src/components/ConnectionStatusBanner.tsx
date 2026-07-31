import { useEffect, useState } from "react";
import { socket } from "../lib/socket";
import {
  getRoomBindingStatus,
  subscribeRoomBinding,
  type RoomBindingStatus,
} from "../lib/roomSessionBinding";

type ConnectionStatus = "connected" | "offline" | "reconnecting" | "failed";

function resolveStatus(
  online: boolean,
  socketConnected: boolean,
  binding: RoomBindingStatus,
): ConnectionStatus {
  if (!online) return "offline";
  if (!socketConnected) return "reconnecting";
  if (binding === "rejoining") return "reconnecting";
  if (binding === "failed") return "failed";
  return "connected";
}

export function ConnectionStatusBanner() {
  const [status, setStatus] = useState<ConnectionStatus>(() =>
    resolveStatus(
      typeof navigator === "undefined" || navigator.onLine,
      socket.connected,
      getRoomBindingStatus(),
    ),
  );

  useEffect(() => {
    const refresh = () => {
      setStatus(resolveStatus(navigator.onLine, socket.connected, getRoomBindingStatus()));
    };

    const unsubscribeBinding = subscribeRoomBinding(refresh);

    socket.on("connect", refresh);
    socket.on("disconnect", refresh);
    socket.on("connect_error", refresh);
    window.addEventListener("offline", refresh);
    window.addEventListener("online", refresh);
    refresh();
    return () => {
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
