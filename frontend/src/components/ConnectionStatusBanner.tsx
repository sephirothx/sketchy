import { connectionStatusText, type ConnectionStatus } from "../lib/connectionStatus";

/** The connection banner, outside a room. When to show it is `placeNotices`'s call. */
export function ConnectionStatusBanner({
  status,
}: {
  status: Exclude<ConnectionStatus, "connected">;
}) {
  return (
    <div className={`connection-status-banner ${status === "failed" ? "reconnecting" : status}`} role="status" aria-live="polite">
      {connectionStatusText(status)}
    </div>
  );
}
