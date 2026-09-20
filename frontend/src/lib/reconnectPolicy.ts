/** How this client comes back after the connection drops, and when it gives up
on a slow server (#872).

A restart used to be met by every client at once: socket.io's defaults put
each first retry 0.5-1.5 s after the close, and each (re)connect costs a
session resolve, presence and block warm-ups, a lobby baseline or a seat
rebind, and two REST refetches - roughly 1,200-1,600 database operations and
800 requests inside a second at 400 sockets, against a pool of ten. And a
server that was merely slow made it worse: three missed `session_ping`s tore
down every seated client's transport and asked for the whole canvas, the most
expensive thing a client can ask for, at the moment the server could least
afford it.

Pure: time and randomness are passed in, and the socket module and the hook
own the timers. */

/** The manager's own backoff for an ordinary drop: first retry after
0.5-1.5 s, doubling, capped at 10 s, each ±50%. Written down rather than left
to socket.io's defaults, which cap at 5 s with a tighter spread. */
export const RECONNECTION_DELAY_MS = 1000;
export const RECONNECTION_DELAY_MAX_MS = 10_000;
export const RECONNECTION_RANDOMIZATION = 0.5;

/** The most a `server_shutdown` notice may ask a client to hold, whatever it
says: past this the client would look broken rather than considerate. */
export const MAX_SHUTDOWN_HOLD_MS = 120_000;

/** How long before the first attempt after the connection closed following a
`server_shutdown` that named `spreadMs`. A uniform draw across the window, so
the replacement process meets its clients as a trickle rather than a spike. */
export function shutdownHoldMs(spreadMs: unknown, random: number): number {
  if (typeof spreadMs !== "number" || !Number.isFinite(spreadMs) || spreadMs <= 0) return 0;
  const window = Math.min(spreadMs, MAX_SHUTDOWN_HOLD_MS);
  return Math.floor(Math.min(Math.max(random, 0), 1) * window);
}

/** How far a reconnect's REST refetches (friends, recovery address) are spread
behind it, so they queue behind the seat rebind rather than beside it. A first
connection does not wait: nothing else is competing for it. */
export const POST_RECONNECT_JITTER_MS = 3000;

export function postReconnectDelayMs(isReconnect: boolean, random: number): number {
  if (!isReconnect) return 0;
  return Math.floor(Math.min(Math.max(random, 0), 1) * POST_RECONNECT_JITTER_MS);
}

/** How long a room waits for the server to come back after it said it was
restarting, before the seat is marked as failed. A deploy is the drain plus a
boot; the ordinary 8 s would show the failed card before the replacement was
even listening. */
export const RESTART_PATIENCE_MS = 60_000;

/** Whether the transport is still being kept alive by the server.

Engine.IO's own ping arrives every `pingInterval` for as long as the server is
reading the connection, however slow it is at answering commands. Seen within
an interval plus the timeout it allows, the transport is alive: missed
`session_ping`s then mean a slow server, not a dead connection. */
export function transportAlive(
  lastPingAt: number | null,
  now: number,
  pingWindowMs: number,
): boolean {
  if (lastPingAt === null) return false;
  return now - lastPingAt <= pingWindowMs;
}

/** Engine.IO's interval plus timeout (25 s + 20 s), for an engine that has not
said its own. One number on purpose: the drawing-limit E2E finds the canvas
limit by its minified literal, which a separate 25-second constant would
duplicate. */
export const DEFAULT_PING_WINDOW_MS = 45_000;

/** The window from what the engine was told at its handshake, if it was. */
export function pingWindowMs(interval: unknown, timeout: unknown): number {
  const valid = (value: unknown): value is number =>
    typeof value === "number" && Number.isFinite(value) && value > 0;
  return valid(interval) && valid(timeout) ? interval + timeout : DEFAULT_PING_WINDOW_MS;
}

/** What a run of missed `session_ping`s leads to. */
export type HeartbeatAction = "none" | "soft-rebind" | "restart";

/** How many consecutive misses it takes before anything is done. */
export const HEARTBEAT_FAILURES_TO_ACT = 3;
export const ESCALATION_BASE_MS = 5000;
export const ESCALATION_MAX_MS = 60_000;

export interface HeartbeatEscalation {
  action: HeartbeatAction;
  /** How many escalations this run has had, counting this one. */
  escalations: number;
  /** When the next escalation may happen at the earliest. */
  notBefore: number;
}

/** Decide what a missed probe leads to (#872).

Nothing until `HEARTBEAT_FAILURES_TO_ACT` in a row, and nothing before
`notBefore`. Then: a **soft rebind** while the transport is alive - one cheap
`join_room` that repairs the binding without a teardown or a canvas dump -
and a **transport restart** only once it has gone silent. Each escalation
pushes the next one out, doubling from 5 s to a minute with ±50% jitter, so a
slow server is asked less often the slower it gets rather than more. A
successful probe resets the run (the hook passes `escalations: 0`). */
export function escalateHeartbeat(options: {
  failures: number;
  escalations: number;
  notBefore: number;
  now: number;
  transportAlive: boolean;
  random: number;
}): HeartbeatEscalation {
  const { failures, escalations, notBefore, now, random } = options;
  if (failures < HEARTBEAT_FAILURES_TO_ACT || now < notBefore) {
    return { action: "none", escalations, notBefore };
  }
  const next = escalations + 1;
  const base = Math.min(ESCALATION_BASE_MS * 2 ** (next - 1), ESCALATION_MAX_MS);
  const jitter = 0.5 + Math.min(Math.max(random, 0), 1);
  return {
    action: options.transportAlive ? "soft-rebind" : "restart",
    escalations: next,
    notBefore: now + Math.floor(base * jitter),
  };
}

/** What a failed rebind leads to (#872): a heartbeat's soft rebind on a
transport the server is still keeping alive leaves the transport alone, and
anything else falls back to a restart and a full rejoin. */
export function afterFailedRebind(options: {
  keepTransport: boolean;
  transportAlive: boolean;
}): "keep" | "restart" {
  return options.keepTransport && options.transportAlive ? "keep" : "restart";
}

/** What this client knows about a planned restart, from the notice to the
replacement connection (#872).

A latch rather than a reading of the disconnect: once `server_shutdown` has
arrived, *every* way back - the server closing the socket, or one of the
client's own recoveries (a phase stall, an exhausted canvas sync) closing it
first during the drain - waits behind the same randomized hold, and a room
waits out the deploy before calling its seat failed. It clears only on a
connection that follows a close, so a socket told at its handshake, mid-drain,
keeps it. */
export interface RestartLatch {
  /** `server_shutdown` arrived, naming this spread. */
  noteNotice(spreadMs: unknown): void;
  /** The connection closed. Returns the hold to apply to the next attempt,
  from now: drawn once per restart, so a second close in the same outage
  does not draw a fresh wait. Zero when no restart is announced. */
  noteClose(now: number, random: number): number;
  /** A connection landed. */
  noteConnect(): void;
  /** How long a connection attempt must still wait. */
  holdRemainingMs(now: number): number;
  /** Whether the server said it was restarting and has not come back yet. */
  restartExpected(): boolean;
}

export function createRestartLatch(): RestartLatch {
  let spread: number | null = null;
  let closed = false;
  let holdUntil = 0;
  return {
    noteNotice(spreadMs) {
      spread = typeof spreadMs === "number" ? spreadMs : 0;
      closed = false;
      holdUntil = 0;
    },
    noteClose(now, random) {
      if (spread === null) return 0;
      if (!closed) {
        closed = true;
        holdUntil = now + shutdownHoldMs(spread, random);
      }
      return Math.max(0, holdUntil - now);
    },
    noteConnect() {
      if (spread === null || !closed) return;
      spread = null;
      closed = false;
      holdUntil = 0;
    },
    holdRemainingMs(now) {
      return spread === null || !closed ? 0 : Math.max(0, holdUntil - now);
    },
    restartExpected() {
      return spread !== null && closed;
    },
  };
}


/** Whether a network coming back, or a page restored from the back/forward
cache, should connect right now (#886).

It should: the backoff it would otherwise wait out was measured against a
network that is no longer the one in front of it. Except during a planned
restart, where the hold this client drew is the whole point of the spread
(R-CONN-14) - a device waking mid-deploy must not turn it into everybody at
once - and except on a tab that has been told to reload, whose socket is
down for good. */
export function shouldReconnectImmediately(state: {
  connected: boolean;
  updateRequired: boolean;
  restartExpected: boolean;
}): boolean {
  return !state.connected && !state.updateRequired && !state.restartExpected;
}
