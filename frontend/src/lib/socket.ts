import { io, Socket } from "socket.io-client";
import { recordClientError } from "./clientErrorLog.ts";
import { PROTOCOL_VERSION, handleUpgradeRequired } from "./protocol.ts";
import type { UpgradeRequiredNotice } from "./protocol.ts";
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
  // Settled at the handshake, where there is somewhere to put the answer. A
  // frame refused by the codec is refused inside a handler with no
  // acknowledgement, so a stale build is never told and diverges in silence.
  auth: { protocol: PROTOCOL_VERSION },
});

// Registered here rather than in a component so the flag is set by the very
// first `connect`, whatever mounts when: it tells "still opening the first
// connection" apart from "the connection dropped", which look identical from
// `socket.connected` alone.
let everConnected = false;
socket.on("connect", () => {
  if (everConnected) telemetry.reconnects += 1;
  everConnected = true;
});

/** True once this page load has completed at least one handshake. */
export function hasEverConnected(): boolean {
  return everConnected;
}

/** What this page load's connection has actually been through.

Kept here rather than in a store because nothing renders it: it exists so that
a bug report saying "it froze" can also say the socket had dropped four times in
the previous minute, which is usually the whole answer. */
const telemetry = {
  reconnects: 0,
  lastDisconnectAt: null as string | null,
  lastDisconnectReason: null as string | null,
};

socket.on("disconnect", (reason) => {
  telemetry.lastDisconnectAt = new Date().toISOString();
  telemetry.lastDisconnectReason = String(reason);
  recordClientError("socket", `disconnect: ${reason}`);
});

socket.on("connect_error", (error) => {
  recordClientError("socket", `connect_error: ${error?.message ?? error}`);
});

// Registered here rather than in a component because a version skew is not
// scoped to any screen: the socket can be told to upgrade while the player is
// in the lobby, mid-game, or on the invite page.
socket.on("upgrade_required", (notice: UpgradeRequiredNotice | undefined) => {
  recordClientError(
    "socket",
    `upgrade_required: expected ${notice?.expected}, sent ${notice?.received}`,
  );
  handleUpgradeRequired(notice, {
    storage: typeof sessionStorage === "undefined" ? null : sessionStorage,
    reload: () => window.location.reload(),
    onStuck: () => {
      recordClientError(
        "socket",
        "upgrade_required repeated after a reload; the bundle is not updating",
      );
    },
  });
});

export interface ConnectionTelemetry {
  connected: boolean;
  everConnected: boolean;
  /** Handshakes after the first. Zero on a connection that never dropped. */
  reconnects: number;
  lastDisconnectAt: string | null;
  lastDisconnectReason: string | null;
  /** "websocket" or "polling" - a game that fell back to polling behaves
      differently enough to be worth knowing before reproducing anything. */
  transport: string | null;
}

export function connectionTelemetry(): ConnectionTelemetry {
  return {
    connected: socket.connected,
    everConnected,
    reconnects: telemetry.reconnects,
    lastDisconnectAt: telemetry.lastDisconnectAt,
    lastDisconnectReason: telemetry.lastDisconnectReason,
    transport: socket.io?.engine?.transport?.name ?? null,
  };
}

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

/** The slice of a Socket.IO client an acknowledged request actually uses.

Named so a test can supply one. The connection states that matter here -
already disconnected, dropping mid-flight, never answering - are precisely the
ones a real socket will not hold still in. */
export interface AckTarget {
  readonly connected: boolean;
  on(event: "disconnect" | "connect", listener: () => void): unknown;
  off(event: "disconnect" | "connect", listener: () => void): unknown;
  emit(event: string, data: unknown, ack: (response: unknown) => void): unknown;
}

/** Emit an event and await its acknowledgement without allowing callers to hang forever. */
export function emitWithAckOn<T = AckResponse>(
  target: AckTarget,
  event: string,
  data: unknown,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  // `=== false` rather than a truthiness check: hosts other than a browser
  // define `navigator` without `onLine`, and a missing flag is not evidence of
  // being offline.
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return Promise.reject(new SocketRequestError("disconnected", "Browser reports no network connection"));
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const timeoutMs = options.timeoutMs ?? DEFAULT_ACK_TIMEOUT_MS;

    function cleanup() {
      clearTimeout(timeout);
      target.off("disconnect", onDisconnect);
      target.off("connect", onConnect);
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

    // Emitting on a disconnected socket does not fail: Socket.IO queues the
    // packet and delivers it on reconnect, and no `disconnect` event arrives
    // to reject against because the disconnect already happened. The timeout
    // would then reject this promise while leaving the packet queued - the
    // player is told the action failed and it happens anyway, seconds later.
    // On this path that means a second room, or a game started twice.
    //
    // So nothing is handed to the socket until it is connected. Waiting rather
    // than refusing keeps the first connection working, where not-yet-
    // connected is the normal state and the queue was doing the right thing;
    // if the timeout wins the race instead, there is no packet to deliver.
    function send() {
      target.on("disconnect", onDisconnect);
      target.emit(event, data, (response: unknown) => finish(() => resolve(response as T)));
    }

    function onConnect() {
      target.off("connect", onConnect);
      if (!settled) send();
    }

    if (target.connected) send();
    else target.on("connect", onConnect);
  });
}

export function emitWithAck<T = AckResponse>(
  event: string,
  data: unknown,
  options: { timeoutMs?: number } = {},
): Promise<T> {
  return emitWithAckOn<T>(socket as unknown as AckTarget, event, data, options);
}

/** Emit an action that only makes sense right now, dropping it if the socket
is down rather than letting Socket.IO deliver it on reconnect.

A buffered packet is replayed into whatever the room has become in the
meantime: a vote cast in a turn that has ended, a guess against a prompt nobody
is drawing any more, a `leave_room` that evicts the player from the room they
just rejoined. Live drawing is deliberately not routed through here - its
frames carry a generation and sequence the server checks, and it has an
explicit resync path, so replay is already answered there. */
export function emitTransient(event: string, ...args: unknown[]): void {
  socket.volatile.emit(event, ...args);
}
