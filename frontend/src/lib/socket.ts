import { io, Socket } from "socket.io-client";
import type { AckResponse } from "../types";

// No URL: connect to the origin that served the page. The backend serves the
// frontend in production and E2E, and the Vite dev server proxies /socket.io,
// so this is same-origin everywhere and carries the session cookie unchanged.
//
// autoConnect is off because the handshake reads the session cookie exactly
// once, and on a first visit that cookie does not exist until GET /api/auth/me
// has provisioned the account. Connecting eagerly would bind the socket to no
// account at all, so the seat it takes could never be reclaimed after signing
// up. App.tsx connects as soon as identity has settled.
export const socket: Socket = io({
  autoConnect: false,
  transports: ["websocket", "polling"],
});

export const DEFAULT_ACK_TIMEOUT_MS = 8000;

export type SocketRequestErrorCode = "disconnected" | "timeout";

export class SocketRequestError extends Error {
  readonly code: SocketRequestErrorCode;

  constructor(code: SocketRequestErrorCode, message: string) {
    super(message);
    this.name = "SocketRequestError";
    this.code = code;
  }
}

export function socketRequestErrorMessage(error: unknown, action: string): string {
  if (error instanceof SocketRequestError) {
    if (error.code === "disconnected") return `Connection lost while trying to ${action}. Please try again.`;
    return `The request to ${action} timed out. Please try again.`;
  }
  return `Could not ${action}. Please try again.`;
}

/** Emit an event and await its acknowledgement without allowing callers to hang forever. */
export function emitWithAck<T = AckResponse>(
  event: string,
  data: unknown,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    return Promise.reject(new SocketRequestError("disconnected", "Browser is offline"));
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const timeoutMs = options.timeoutMs ?? DEFAULT_ACK_TIMEOUT_MS;

    function cleanup() {
      clearTimeout(timeout);
      socket.off("disconnect", onDisconnect);
    }

    function finish(callback: () => void) {
      if (settled) return;
      settled = true;
      cleanup();
      callback();
    }

    function onDisconnect() {
      finish(() => reject(new SocketRequestError("disconnected", "Socket disconnected before acknowledgement")));
    }

    const timeout = setTimeout(() => {
      finish(() => reject(new SocketRequestError("timeout", `No acknowledgement for ${event}`)));
    }, timeoutMs);

    socket.on("disconnect", onDisconnect);
    socket.emit(event, data, (response: T) => finish(() => resolve(response)));
  });
}
