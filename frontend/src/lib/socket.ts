import { io, Socket } from "socket.io-client";
import { applyClientConfig } from "./clientConfig.ts";
import { recordClientError } from "./clientErrorLog.ts";
import {
  HEALTH_REPORT_INTERVAL_MS,
  noteHealth,
  takeHealthReport,
} from "./connectionHealth.ts";
import { PROTOCOL_VERSION, handleUpgradeRequired } from "./protocol.ts";
import { isUpdateRequired, markUpdateRequired } from "./updateRequired.ts";
import type { UpgradeRequiredNotice } from "./protocol.ts";
import type { AckResponse } from "../types";
import { ui } from "../content/ui/index.ts";
import { applyPrivateResult } from "./privateResults.ts";
import {
  RECONNECTION_DELAY_MAX_MS,
  RECONNECTION_DELAY_MS,
  RECONNECTION_RANDOMIZATION,
  pingWindowMs,
  attemptIsInFlight,
  createRestartLatch,
  postReconnectDelayMs,
  serverCloseRetryDelayMs,
  shouldReconnectImmediately,
  transportAlive,
} from "./reconnectPolicy.ts";

// No URL: connect to the origin that served the page. The backend serves the
// frontend in production and E2E, and the Vite dev server proxies /socket.io,
// so this is same-origin everywhere and carries the session cookie unchanged.
//
// autoConnect is off because the handshake reads the session cookie exactly
// once, and on a first visit that cookie does not exist until GET /api/auth/me
// has provisioned the account. Connecting eagerly would bind the socket to no
// account at all, so the seat it takes could never be reclaimed after signing
// up. App.tsx connects as soon as identity has settled.
/** How long one connection attempt may stall before polling is put first.
Engine.IO's default connect timeout is 20 s, which on a network that silently
drops WebSocket upgrades is 20 s of nothing before polling is even
considered. Under the 8 s an acknowledged command waits for the connection
(`DEFAULT_ACK_TIMEOUT_MS`), so a join pressed during the stall still lands on
the polling session instead of timing out first. A healthy WebSocket
handshake takes well under a second; a slow network that trips this merely
starts on polling and is upgraded from there. */
export const CONNECT_TIMEOUT_MS = 6_000;

/** The version this socket claims, which is the bundle's - except under test.

A stale client cannot be built from the current tree, so the E2E suite's
diagnostics build (the same flag that arms the crash probe) lets a page claim
an older version from `sessionStorage`: the server then treats the tab as a
build from before the last deploy, and everything downstream of that - the
notice, the refusals, the close, the reload-once rule - is the real thing. A
production build never reads the key. */
export const PROTOCOL_OVERRIDE_KEY = "sketchy:protocol-override";

// Read through an optional chain: the unit tests import this module under
// Node, where `import.meta.env` does not exist; Vite still inlines it.
const diagnosticsBuild =
  (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_RENDER_DIAGNOSTICS === "true";

function claimedProtocolVersion(): number {
  if (!diagnosticsBuild) return PROTOCOL_VERSION;
  try {
    const raw = sessionStorage.getItem(PROTOCOL_OVERRIDE_KEY);
    if (raw !== null && /^\d+$/.test(raw)) return Number(raw);
  } catch {
    // No storage, no override.
  }
  return PROTOCOL_VERSION;
}

export const socket: Socket = io({
  autoConnect: false,
  // WebSocket first, and polling *actually* tried when it fails (#601).
  // Listing both is not enough: without `tryAllTransports` the client only
  // moves to the next transport when the first fails while opening, and
  // an environment that blocks WebSocket upgrades kept retrying WebSocket
  // for ever against a polling fallback it had been told about. A
  // successful WebSocket costs nothing more; polling costs more bytes and is
  // a working session instead of none. An application refusal at the
  // handshake (a suspension, a version skew) is not a transport error and
  // never causes a transport switch.
  transports: ["websocket", "polling"],
  tryAllTransports: true,
  timeout: CONNECT_TIMEOUT_MS,
  // An ordinary drop's backoff, written down rather than left to the
  // library's defaults (#872, `reconnectPolicy.ts`).
  reconnectionDelay: RECONNECTION_DELAY_MS,
  reconnectionDelayMax: RECONNECTION_DELAY_MAX_MS,
  randomizationFactor: RECONNECTION_RANDOMIZATION,
  // Settled at the handshake, where there is somewhere to put the answer. A
  // frame refused by the codec is refused inside a handler with no
  // acknowledgement, so a stale build is never told and diverges in silence.
  auth: { protocol: claimedProtocolVersion() },
});

// The E2E suite reads the socket's own state through this in a diagnostics
// build (whether it is connected, whether it will reconnect) rather than
// inferring it from network activity. Never installed in a production build.
if (diagnosticsBuild) {
  (window as Window & { __SKETCHY_SOCKET__?: Socket }).__SKETCHY_SOCKET__ = socket;
}

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

// --- after a planned restart (#872) ---------------------------------------
//
// From `server_shutdown` until the replacement connection lands, every way
// back waits behind one randomized hold (`createRestartLatch`) - whichever
// side closes the socket. The server closing it is held through the manager's
// own backoff below; a close this client made itself (a phase stall, an
// exhausted canvas sync) is held by `socket.connect` further down.
const restart = createRestartLatch();
socket.on("server_shutdown", (payload: unknown) => {
  restart.noteNotice((payload as { reconnectSpreadMs?: unknown } | null)?.reconnectSpreadMs);
});
socket.on("disconnect", (reason) => {
  const hold = restart.noteClose(Date.now(), Math.random());
  if (hold <= 0 || reason === "io client disconnect") return;
  // The manager schedules its first retry right after this event, from its
  // backoff - so for that one attempt the backoff *is* the hold: a random
  // point in the window the server named, exactly. A `connect()` called
  // meanwhile (a room rebinding) waits on that pending retry rather than
  // opening one of its own, so nothing jumps the queue.
  socket.io.reconnectionDelay(hold);
  socket.io.reconnectionDelayMax(hold);
  socket.io.randomizationFactor(0);
});
// Back to the ordinary backoff once the held attempt has been spent - by the
// manager's own retry, by a `connect()` that waited the hold out (a named
// visitor's re-handshake cancels the manager's retry, so no
// `reconnect_attempt` ever comes), or by a connection landing. Left behind,
// the hold would become every later retry's fixed delay, up to two minutes.
function restoreOrdinaryBackoff(): void {
  socket.io.reconnectionDelay(RECONNECTION_DELAY_MS);
  socket.io.reconnectionDelayMax(RECONNECTION_DELAY_MAX_MS);
  socket.io.randomizationFactor(RECONNECTION_RANDOMIZATION);
}
socket.io.on("reconnect_attempt", restoreOrdinaryBackoff);
socket.on("connect", () => {
  restart.noteConnect();
  restoreOrdinaryBackoff();
});


// The network came back, or the page came out of the back/forward cache
// (#886). Either way the backoff this connection was waiting out describes a
// network that no longer exists: try now rather than in up to ten seconds.
// Guarded on the method, not the object: a unit test may stand `window` up as
// the module scope to give `apiRequest` a timer.
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  const reconnectNow = () => {
    const now = {
      connected: socket.connected,
      updateRequired: isUpdateRequired(),
      restartExpected: restart.restartExpected(),
      attemptInFlight: attemptIsInFlight(managerReadyState()),
    };
    if (!shouldReconnectImmediately(now)) return;
    restoreOrdinaryBackoff();
    // Through a close, because a bare `connect()` here does nothing at all:
    // `Socket.connect()` skips `Manager.open()` while the manager is
    // reconnecting, and `open()` returns early while an attempt is in flight -
    // between them that is every state a waiting client is in, so the handler
    // was a no-op and the whole point of it (#886: connect now rather than in
    // up to ten seconds) never fired. `disconnect()` cancels the pending retry
    // and its backoff; `connect()` then opens one attempt immediately. The
    // guard above is what keeps that close from aborting a handshake that is
    // already under way.
    socket.disconnect();
    socket.connect();
  };
  window.addEventListener("online", reconnectNow);
  window.addEventListener("pageshow", (event) => {
    if ((event as PageTransitionEvent).persisted) reconnectNow();
  });
}

/** Whether the server said it was restarting and has not come back yet. A
room then waits out a deploy before giving up. */
export function restartExpected(): boolean {
  return restart.restartExpected();
}

/** Run *handler* on every connection, spread behind a reconnect (#872).

For the REST refetches a reconnect triggers - friends, the recovery address -
which would otherwise land beside the seat rebind, from every client at once.
The first connection runs it immediately. Returns the unsubscribe. */
export function onConnectSpread(handler: () => void): () => void {
  let timer: number | null = null;
  const run = () => {
    if (timer !== null) window.clearTimeout(timer);
    const delay = postReconnectDelayMs(telemetry.reconnects > 0, Math.random());
    if (delay === 0) {
      timer = null;
      handler();
      return;
    }
    timer = window.setTimeout(() => {
      timer = null;
      handler();
    }, delay);
  };
  socket.on("connect", run);
  return () => {
    socket.off("connect", run);
    if (timer !== null) window.clearTimeout(timer);
  };
}

// When the server last kept the transport alive with Engine.IO's own ping.
let lastTransportPingAt: number | null = null;
socket.io.on("ping", () => {
  lastTransportPingAt = Date.now();
});
socket.io.on("open", () => {
  lastTransportPingAt = Date.now();
});

/** Whether the server is still reading this connection, however slowly it is
answering commands: missed `session_ping`s then mean slow, not dead (#872). */
export function transportIsAlive(now = Date.now()): boolean {
  const engine = socket.io.engine as unknown as
    | { _pingInterval?: number; _pingTimeout?: number }
    | undefined;
  const window = pingWindowMs(engine?._pingInterval, engine?._pingTimeout);
  return socket.connected && transportAlive(lastTransportPingAt, now, window);
}

/** What this page load's connection has actually been through.

Kept here rather than in a store because nothing renders it: it exists so that
a bug report saying "it froze" can also say the socket had dropped four times in
the previous minute, which is usually the whole answer. */
const telemetry = {
  reconnects: 0,
  lastDisconnectAt: null as string | null,
  lastDisconnectReason: null as string | null,
  /** The transport each handshake opened on, newest last, bounded. A page
  that reads "polling, websocket, polling" fell back and recovered. */
  transports: [] as string[],
  /** Times a polling session was upgraded to WebSocket afterwards. */
  upgrades: 0,
  /** Times a stalled WebSocket attempt made the client put polling first. */
  fallbacks: 0,
};

socket.io.on("open", () => {
  const name = socket.io.engine?.transport?.name ?? "unknown";
  telemetry.transports.push(name);
  if (telemetry.transports.length > 8) telemetry.transports.shift();
  if (name !== "websocket") recordClientError("socket", `connected over ${name}`);
  socket.io.engine?.once("upgrade", () => {
    telemetry.upgrades += 1;
  });
});

socket.on("disconnect", (reason) => {
  telemetry.lastDisconnectAt = new Date().toISOString();
  telemetry.lastDisconnectReason = String(reason);
  recordClientError("socket", `disconnect: ${reason}`);
});

/** Which transports to try next after a failed connection attempt (#601).

`tryAllTransports` moves on when the WebSocket *errors* while opening, which is
what a proxy answering the upgrade with an HTTP status produces. A network that
silently drops upgrades produces nothing at all: the socket hangs, the attempt
times out, and Engine.IO retries WebSocket for ever, because a timeout is not a
transport error. So a timeout on an attempt whose engine never opened puts
polling first for the next attempt; Engine.IO still probes for a WebSocket
upgrade from there, and keeps polling if that probe hangs too. An application
refusal - a suspension, a version skew - arrives over a transport that did
open, and changes nothing here: another transport would be refused the same. */
export function transportsAfterStall(
  current: readonly string[],
  engineOpened: boolean,
): string[] {
  if (engineOpened) return [...current];
  if (current[0] !== "websocket" || !current.includes("polling")) return [...current];
  return ["polling", "websocket"];
}

// The watchdog. Armed on every attempt by wrapping the manager's `open`,
// which the first connect and each reconnect go through; disarmed by the
// engine handshake completing, or the attempt ending in an error or a close
// on its own. When it fires, the attempt stalled: nothing arrived in
// CONNECT_TIMEOUT_MS on a transport the browser reported open.
let stallTimer: number | null = null;

function disarmStallWatchdog(): void {
  if (stallTimer !== null) {
    window.clearTimeout(stallTimer);
    stallTimer = null;
  }
}

function armStallWatchdog(): void {
  disarmStallWatchdog();
  stallTimer = window.setTimeout(() => {
    stallTimer = null;
    if (socket.connected) return;
    const opts = socket.io.opts as { transports?: string[] };
    const next = transportsAfterStall(opts.transports ?? [], socket.io.engine?.readyState === "open");
    if (!opts.transports || next[0] === opts.transports[0]) return;
    opts.transports = next;
    recordClientError("socket", `transport fallback: the ${opts.transports[1]} attempt stalled, trying polling first`);
    telemetry.fallbacks += 1;
    noteHealth("stallFallbacks");
    // A fresh engine reads the new order; nothing was connected, so nobody
    // sees a disconnect.
    socket.disconnect();
    socket.connect();
  }, CONNECT_TIMEOUT_MS);
}

/** The manager's own `_readyState`: "closed", "opening" or "open". */
function managerReadyState(): string | undefined {
  return (socket.io as unknown as { _readyState?: string })._readyState;
}

const managerOpen = socket.io.open.bind(socket.io);
socket.io.open = ((callback?: (err?: Error) => void) => {
  // Only an attempt that actually starts is watched: `connect()` on a socket
  // already open or opening is a no-op in the manager and must not arm a
  // timer against a connection that is fine.
  if (!attemptIsInFlight(managerReadyState())) armStallWatchdog();
  return managerOpen(callback);
}) as typeof socket.io.open;
socket.io.on("open", disarmStallWatchdog);
socket.io.on("error", disarmStallWatchdog);
socket.io.on("close", disarmStallWatchdog);

socket.on("connect_error", (error) => {
  recordClientError("socket", `connect_error: ${error?.message ?? error}`);
});

// Registered here rather than in a component because a version skew is not
// scoped to any screen: the socket can be told to upgrade while the player is
// in the lobby, mid-game, or on the invite page.
// This page load's upgrade reload, once asked for (#1056).
const upgradeReload = { pending: false };

socket.on("upgrade_required", (notice: UpgradeRequiredNotice | undefined) => {
  recordClientError(
    "socket",
    `upgrade_required: expected ${notice?.expected}, sent ${notice?.received}`,
  );
  handleUpgradeRequired(notice, {
    storage: typeof sessionStorage === "undefined" ? null : sessionStorage,
    reload: () => window.location.reload(),
    reloadInFlight: upgradeReload,
    onStuck: () => {
      recordClientError(
        "socket",
        "upgrade_required repeated after a reload; the bundle is not updating",
      );
      noteUpdateStuck();
    },
  });
});

/** The reload did not fetch a compatible bundle: stop and say so (#476).

The server refuses everything this socket says and closes it in a few
seconds; reconnecting would only be told the same thing and closed again,
a loop that costs a handshake every few seconds for nothing. So the socket is
put down for good - `disconnect()` on a manager with reconnection off stays
down - and the page shows the way out, which is a reload the player chooses. */
function noteUpdateStuck(): void {
  socket.io.reconnection(false);
  socket.disconnect();
  markUpdateRequired();
}

// Down for good means down against every caller, not only the manager's
// own reconnection: the page opens the socket by hand after its first
// account read, after a sign-in, and when the stall watchdog fires, and
// each of those would otherwise open one more handshake for the server to
// refuse and close. So the method itself refuses once the tab is stuck.
// And a planned restart's hold is kept against every caller too (#872): a
// connection closed by this client during a drain, then reopened by hand,
// would otherwise skip the spread the server asked for. One deferred attempt
// however many callers ask; it lands on the manager's pending retry if the
// server closed the socket, which makes it a no-op there.
const rawConnect = socket.connect.bind(socket);
let heldConnect: number | null = null;
socket.connect = (() => {
  if (isUpdateRequired()) return socket;
  const wait = restart.holdRemainingMs(Date.now());
  if (wait <= 0) {
    restoreOrdinaryBackoff();
    return rawConnect();
  }
  if (heldConnect === null) {
    heldConnect = window.setTimeout(() => {
      heldConnect = null;
      socket.connect();
    }, wait);
  }
  return socket;
}) as typeof socket.connect;

/** Where the REST layer reports the same stuck state. */
export function noteUpdateStuckFromRest(): void {
  noteUpdateStuck();
}

// Same reasoning as the two notices above: the cadences arrive at the
// handshake, which is usually before anything that depends on them has
// mounted, so they are read where the socket lives and handed on from there.
socket.on("client_config", (payload: unknown) => {
  applyClientConfig(payload);
});

let serverFullReason: string | null = null;
const serverFullListeners = new Set<(reason: string | null) => void>();

// Same reasoning as the upgrade notice above: being turned away for capacity
// is not scoped to a screen, and the socket is closed immediately afterwards,
// so this has to be read where the socket lives rather than in a component
// that may not be mounted.
// One meaning, so the sentence is written here: the payload's `reason` is
// English, for a log (R-I18N-01).
// Whether this very handshake was turned away: `server_full` is emitted
// inside the server's connect handler and delivered before this socket's
// `connect` event, so a `connect` that follows it is the turned-away socket's
// own, not an admission (review of #1053). Reset when the transport opens.
let turnedAwayThisHandshake = false;
socket.io.on("open", () => {
  turnedAwayThisHandshake = false;
});
socket.on("server_full", () => {
  recordClientError("socket", "server_full");
  turnedAwayThisHandshake = true;
  serverFullReason = ui.socket.sketchyIsFullRightNow;
  serverFullListeners.forEach((listener) => listener(serverFullReason));
});

// --- a socket the server closed comes back (#998) ---------------------------
//
// The manager treats `io server disconnect` as final, and every server-side
// close that is not a refusal - another tab taking the seat, a kick, the
// capacity ceiling, a stale socket that never reloaded - left this tab with
// a socket nothing reopened. The policy decides whether and when; the
// wrapped `connect` below still honours a planned restart's hold and a stuck
// update.
let serverCloseAttempts = 0;
let serverCloseTimer: number | null = null;
socket.on("connect", () => {
  serverCloseAttempts = 0;
  if (serverCloseTimer !== null) {
    window.clearTimeout(serverCloseTimer);
    serverCloseTimer = null;
  }
  if (serverFullReason !== null && !turnedAwayThisHandshake) {
    // Back in: the banner that said the server was full is stale. Not on
    // the `connect` of the socket being turned away, which the notice
    // precedes: that one keeps the banner, and its close keeps the 30 s
    // first retry.
    serverFullReason = null;
    serverFullListeners.forEach((listener) => listener(null));
  }
});
socket.on("disconnect", (reason) => {
  const wait = serverCloseRetryDelayMs({
    reason,
    attempt: serverCloseAttempts,
    updateRequired: isUpdateRequired(),
    turnedAwayForCapacity: serverFullReason !== null,
    random: Math.random(),
    reloadPending: upgradeReload.pending,
  });
  if (wait === null) return;
  serverCloseAttempts += 1;
  if (serverCloseTimer !== null) window.clearTimeout(serverCloseTimer);
  serverCloseTimer = window.setTimeout(() => {
    serverCloseTimer = null;
    if (socket.connected || attemptIsInFlight(managerReadyState())) return;
    socket.connect();
  }, wait);
});

/** The transport this session is on, or null before one is open. Read by the
drawing cadence (#887): a flush on long-polling is an HTTP POST. */
export function currentTransport(): string | null {
  return socket.io?.engine?.transport?.name ?? null;
}

/** Subscribe to the transport changing: a new connection, or a polling
session upgrading to WebSocket under it (#887). */
export function onTransportChange(listener: (transport: string | null) => void): () => void {
  const tell = () => listener(currentTransport());
  const watchEngine = () => {
    tell();
    socket.io.engine?.on("upgrade", tell);
  };
  socket.on("connect", tell);
  socket.io.on("open", watchEngine);
  if (socket.connected) watchEngine();
  return () => {
    socket.off("connect", tell);
    socket.io.off("open", watchEngine);
    socket.io.engine?.off("upgrade", tell);
  };
}

/** The reason this client was turned away, if it was. */
export function currentServerFullReason(): string | null {
  return serverFullReason;
}

/** Subscribe to being turned away - and, with null, to getting back in.
Called immediately if it already happened. */
export function onServerFull(listener: (reason: string | null) => void): () => void {
  serverFullListeners.add(listener);
  if (serverFullReason !== null) listener(serverFullReason);
  return () => {
    serverFullListeners.delete(listener);
  };
}

/**
 * Re-handshake so the socket picks up an account it did not have.
 *
 * The server reads the session cookie once, at the handshake, and keeps the
 * account on the socket session from then on. A visitor who arrives with no
 * account connects as nobody - and since provisioning now happens when they
 * choose a name, that is the ordinary first visit rather than a rarity. Left
 * alone, the socket would stay anonymous for its whole life and refuse to
 * open a room for somebody who plainly has an account.
 */
export function reconnectWithCurrentIdentity(): void {
  socket.disconnect();
  socket.connect();
}

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
  /** The transport each handshake of this page load opened on, newest last. */
  transports: string[];
  /** Polling sessions later upgraded to WebSocket. */
  upgrades: number;
  /** Stalled WebSocket attempts that made the client put polling first. */
  fallbacks: number;
}

export function connectionTelemetry(): ConnectionTelemetry {
  return {
    connected: socket.connected,
    everConnected,
    reconnects: telemetry.reconnects,
    lastDisconnectAt: telemetry.lastDisconnectAt,
    lastDisconnectReason: telemetry.lastDisconnectReason,
    transport: socket.io?.engine?.transport?.name ?? null,
    transports: [...telemetry.transports],
    upgrades: telemetry.upgrades,
    fallbacks: telemetry.fallbacks,
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
    if (error.code === "disconnected") return ui.socket.connectionLostWhileTryingTo({ action });
    return ui.socket.theRequestToActionTimed({ action });
  }
  return ui.socket.couldNotActionPleaseTry({ action });
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
  options: { timeoutMs?: number; onLate?: (response: T) => void } = {},
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
      target.emit(event, data, (response: unknown) => {
        // An answer after this promise gave up is not dropped in silence when
        // the caller says what to do with one: the server may have done what
        // the player was told had failed (#879).
        if (settled) options.onLate?.(response as T);
        else finish(() => resolve(response as T));
      });
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
  options: { timeoutMs?: number; onLate?: (response: T) => void } = {},
): Promise<T> {
  return emitWithAckOn<T>(socket as unknown as AckTarget, event, data, options);
}

/** A command that seats this socket somewhere the player chose to go (#879):
`create_room`, `join_room` from the lobby, `join_friend_room`.

The server answers inside six seconds or creates nothing, so a late answer
should never come - but if one does and it says the seat was taken, the player
has already been told it failed and may be somewhere else by now. The seat is
given back by name, so the room they are in now is not the one left. Not for
the room's own rebind (`useRoomSessionReconnect`), whose seat is the one the
player is sitting in. */
export function emitEntry<T = AckResponse>(event: string, data: unknown): Promise<T> {
  return emitWithAck<T>(event, data, {
    onLate: (response) => {
      const answer = response as { ok?: unknown; roomId?: unknown } | null;
      // Transient (R-CONN-06): given back now or not at all, never replayed
      // from a buffer after a reconnect.
      if (answer?.ok === true && typeof answer.roomId === "string") {
        emitTransient("leave_room", { roomId: answer.roomId });
      }
    },
  });
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
  // socket.io discards a volatile packet, without a word, exactly when the
  // transport is not writable: a socket that is down, and on long-polling
  // any moment a POST is in flight. The same test here, so what is counted
  // is what was dropped rather than a guess at it (#876).
  if (!socket.io.engine?.transport?.writable) noteHealth("droppedEmits");
  socket.volatile.emit(event, ...args);
}

// The connection-health report (#876, `connectionHealth.ts`): at most once a
// minute, only when something happened, and only on a socket that is up - a
// report kept for a socket that is down goes with the next one rather than
// being counted as a dropped emit of its own. Not volatile: a volatile packet
// is discarded whenever the transport is not writable, which on long-polling
// is every in-flight POST, so polling reports - the transport this exists to
// diagnose - would be lost more often than the rest. Started by the first
// connection, not at import, so a test that loads this module arms no timer.
let healthTimer: ReturnType<typeof setInterval> | null = null;

function sendHealthReport(): void {
  if (!socket.connected) return;
  const report = takeHealthReport();
  if (report !== null) socket.emit("client_health", report);
}

socket.on("connect", () => {
  if (healthTimer !== null || typeof setInterval !== "function") return;
  healthTimer = setInterval(sendHealthReport, HEALTH_REPORT_INTERVAL_MS);
  // A tab closing takes its last minute with it unless it is sent now;
  // best effort, since a page being unloaded may not get to write it.
  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener("pagehide", sendHealthReport);
  }
});

/** How long a guess waits for the server's acknowledgement before it is resent. */
export const GUESS_ACK_TIMEOUT_MS = 2000;

/** The slice of a Socket.IO client a confirmed transient emit uses.

Named so a test can supply one: the states that matter here - the packet
discarded before it is written, the acknowledgement that never comes, the
connection gone by the time the retry would go out - are exactly the ones a
real socket will not hold still in. */
export interface TransientAckTarget {
  readonly connected: boolean;
  /** Emit volatile, calling back with an error if no ack arrives in `timeoutMs`. */
  emitTransient(event: string, data: unknown, timeoutMs: number, ack: (error: unknown, answer?: unknown) => void): void;
  /** Where a guess made right now belongs, or null when there is no such
  place (not connected, no room, no turn). Read at the first attempt and
  again before a retry (#599). */
  scope(): GuessScope | null;
}

/** The moment a guess was made in: this connection, this room, this turn.
A retry that outlives any of the three is not sent, and the server ignores a
guess that names a room or turn its seat has left. `connected` on its own
says nothing about gameplay: a socket can be replaced, rebind to another
room, or watch the turn end while staying "connected" throughout. */
export interface GuessScope {
  connection: string;
  code: string;
  turnId: string;
}

function sameScope(a: GuessScope, b: GuessScope | null): boolean {
  return b !== null && a.connection === b.connection && a.code === b.code && a.turnId === b.turnId;
}

export interface GuessDeliveryResult {
  /** The guess reached the server - with its private result, if it had one
  (#884). It may still have been ignored there. */
  onDelivered?: (answer?: unknown) => void;
  /** Both attempts went unacknowledged: the guess is lost, and the player should be told. */
  onUndelivered?: () => void;
}

/** Build a guess sender that retries once when delivery goes unacknowledged.

A guess is volatile (see `emitTransient`) because a guess replayed into a turn
that has ended is worse than a guess lost - but volatile also drops the packet
when the transport is merely *momentarily* unwritable, which a mobile player
hits mid-round and which nothing currently reports. The acknowledgement turns
that silence into a signal, and one retry covers the blip.

The retry carries the same `id`, which the server remembers per connection, so
a guess that did arrive is never processed twice. It is sent only inside the
scope the first attempt captured - the same connection, room and turn - and is
abandoned otherwise (#599): `connected` being true at the timeout used to be
the whole test, and a connection replaced before the timeout, a room switched
on the same socket or a turn that ended all passed it, replaying the guess into
whatever the seat was doing by then - the very thing volatile delivery exists
to prevent. The guess also carries its room code and turn id, so the server
ignores a packet whose scope is gone even when the client's check was not
enough. Each result callback settles exactly once. */
export function createGuessSender(
  target: TransientAckTarget,
  options: { timeoutMs?: number; onAnswer?: (answer: unknown) => void } = {},
): (text: string, result?: GuessDeliveryResult) => void {
  const timeoutMs = options.timeoutMs ?? GUESS_ACK_TIMEOUT_MS;
  // Per page load, not per connection: a counter that restarted on reconnect
  // could reissue an id the server still remembers. The server keys its window
  // on the connection, so this only has to never repeat within one.
  let nextGuessId = 0;

  return function sendGuess(text: string, result: GuessDeliveryResult = {}): void {
    const id = nextGuessId++;
    let retriesLeft = 1;
    let settled = false;
    const settle = (delivered: boolean, answer?: unknown) => {
      if (settled) return;
      settled = true;
      if (delivered) {
        // The private result rides the ack (#884); a retry of a guess that
        // did arrive is answered with the same one. Shown only while the
        // guess's own connection, room and turn are current: a late answer
        // from a room left or a turn over would write last turn's receipt
        // into this one - and close its guess input.
        if (
          answer !== undefined
          && answer !== null
          && scope !== null
          && sameScope(scope, target.scope())
        ) options.onAnswer?.(answer);
        result.onDelivered?.(answer);
      } else result.onUndelivered?.();
    };

    const scope = target.scope();
    if (scope === null) {
      settle(false);
      return;
    }

    function attempt() {
      target.emitTransient(
        "guess",
        { text, id, code: scope!.code, turnId: scope!.turnId },
        timeoutMs,
        (error, answer) => {
          if (settled) return; // a late callback from an attempt already judged
          if (!error) {
            settle(true, answer);
            return;
          }
          if (retriesLeft > 0 && target.connected && sameScope(scope!, target.scope())) {
            retriesLeft -= 1;
            attempt();
            return;
          }
          settle(false);
        },
      );
    }

    attempt();
  };
}

/** The shared socket as a guess target. The scope's room and turn come from
whoever knows them - the game store - through `guessScope`, registered by
`lib/guessSender.ts`, so this module does not import the store. */
let guessScope: () => Omit<GuessScope, "connection"> | null = () => null;

export function provideGuessScope(read: () => Omit<GuessScope, "connection"> | null): void {
  guessScope = read;
}

export const sharedGuessTarget: TransientAckTarget = {
  get connected() {
    return socket.connected;
  },
  emitTransient(event, data, timeoutMs, ack) {
    socket.volatile.timeout(timeoutMs).emit(event, data, ack);
  },
  scope() {
    const place = guessScope();
    if (!socket.connected || !socket.id || place === null) return null;
    return { connection: socket.id, ...place };
  },
};

/** Send a guess on the shared socket, retrying once inside the scope it was made in. */
export const sendGuess = createGuessSender(sharedGuessTarget, { onAnswer: applyPrivateResult });
