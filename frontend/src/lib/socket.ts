import { io, Socket } from "socket.io-client";
import { useAuthStore } from "../store/authStore";
import type { AckResponse } from "../types";

export const SERVER_URL = import.meta.env.VITE_SERVER_URL || undefined;

export const socket: Socket = io(SERVER_URL, {
  autoConnect: false,
  withCredentials: true,
  reconnection: true,
  transports: ["websocket", "polling"],
});

export const DEFAULT_ACK_TIMEOUT_MS = 8000;

let sessionBootstrap: Promise<void> | null = null;

export function waitForConnect(timeoutMs = DEFAULT_ACK_TIMEOUT_MS): Promise<void> {
  if (socket.connected) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      socket.off("connect", onConnect);
      reject(new SocketRequestError("timeout", "Socket did not connect"));
    }, timeoutMs);
    function onConnect() {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      socket.off("connect", onConnect);
      resolve();
    }
    socket.once("connect", onConnect);
    socket.connect();
    if (socket.connected) onConnect();
  });
}

/** Provision the guest cookie, then open the Socket.IO connection that will send it. */
export function ensureSession(): Promise<void> {
  if (!sessionBootstrap) {
    sessionBootstrap = (async () => {
      const user = await useAuthStore.getState().fetchMe();
      await waitForConnect();
      if (!user) sessionBootstrap = null;
    })();
  }
  return sessionBootstrap;
}

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
export async function emitWithAck<T = AckResponse>(
  event: string,
  data: unknown,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    throw new SocketRequestError("disconnected", "Browser is offline");
  }

  await ensureSession();
  if (!socket.connected) await waitForConnect();

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
