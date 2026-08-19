/** Decides what the global connection banner should say, and when. */

import type { RoomBindingStatus } from "./roomSessionBinding";

export type ConnectionStatus = "connected" | "offline" | "reconnecting" | "failed";

/**
 * A socket that has never connected is not a socket that dropped: on arrival it
 * waits for `GET /api/auth/me` and the handshake, which is normal and silent.
 * Only announce trouble once that first attempt has clearly overrun.
 */
export const FIRST_CONNECT_GRACE_MS = 3000;

/**
 * Reconnects are usually over in well under a second - socket.io retries on its
 * own, and signing in deliberately bounces the transport - so hold the banner
 * back long enough that the user only sees outages that outlast the recovery.
 */
export const RECONNECT_GRACE_MS = 1000;

export function resolveConnectionStatus(input: {
  online: boolean;
  socketConnected: boolean;
  binding: RoomBindingStatus;
}): ConnectionStatus {
  if (!input.online) return "offline";
  if (!input.socketConnected) return "reconnecting";
  if (input.binding === "rejoining") return "reconnecting";
  if (input.binding === "failed") return "failed";
  return "connected";
}

/** How long `status` must persist before it is worth telling the user about. */
export function connectionBannerDelayMs(status: ConnectionStatus, everConnected: boolean): number {
  if (status !== "reconnecting") return 0;
  return everConnected ? RECONNECT_GRACE_MS : FIRST_CONNECT_GRACE_MS;
}
