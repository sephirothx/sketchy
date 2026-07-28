import { useEffect, useState } from "react";
import { socket } from "../lib/socket";

type ConnectionStatus = "connected" | "offline" | "reconnecting";

export function ConnectionStatusBanner() {
  const [status, setStatus] = useState<ConnectionStatus>(
    typeof navigator !== "undefined" && !navigator.onLine ? "offline" : "connected",
  );

  useEffect(() => {
    const onConnect = () => setStatus("connected");
    const onDisconnect = () => setStatus(navigator.onLine ? "reconnecting" : "offline");
    const onConnectError = () => setStatus(navigator.onLine ? "reconnecting" : "offline");
    const onOffline = () => setStatus("offline");
    const onOnline = () => setStatus(socket.connected ? "connected" : "reconnecting");

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    socket.on("connect_error", onConnectError);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    return () => {
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      socket.off("connect_error", onConnectError);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, []);

  if (status === "connected") return null;
  return (
    <div className={`connection-status-banner ${status}`} role="status" aria-live="polite">
      {status === "offline"
        ? "You’re offline. Check your connection; Sketchy will reconnect automatically."
        : "Connection lost — reconnecting…"}
    </div>
  );
}
