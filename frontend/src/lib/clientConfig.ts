/** Cadences the server decides and the client runs at.

The drawer's flush interval is the one this exists for. It is the largest
single lever on drawing bandwidth, and the value that turned out to be right
was not the one the byte curve pointed at — it was found by looking at a
viewer's screen, and a value only looking can settle is one somebody has to be
able to change while looking. So the server ships it rather than the bundle
compiling it.

Read where the socket lives rather than in a component, for the same reason
`server_full` is: the notice arrives at the handshake, which may be long before
anything that cares has mounted, and a value that arrived early must not be
lost. Subscribers are therefore called immediately with what is already known.

A missing or malformed field falls back to the compiled default. A server that
cannot say is not a reason to stop drawing, and these numbers all have an
answer that has always worked.

Version 2 dropped `lobbyPollIntervalMs`: the lobby is told about rooms over its
channel now (#462) and has no cadence of its own to be given. Version 3 added
the drawing allowance (#597). Version 4 added the AFK input window (#677),
which is the same kind of number for the same reason: only watching somebody
play settles how recently a client must have seen a hand on the controls
before it answers an AFK check on their behalf. */

export interface ClientConfig {
  flushIntervalMs: number;
  /** The drawing allowance a `draw` frame spends: this many frames per
  window. Version 3 (#597) added it so a replay after a stall can pace itself
  under the allowance instead of bursting into a silent refusal. */
  drawingFramesPerWindow: number;
  drawingWindowSeconds: number;
  /** How recently this client must have seen a pointer or a key to answer an
  `afk_check` for the player, rather than asking them. Version 4 (#677). */
  afkInputWindowMs: number;
}

/** What the client uses until a server says otherwise, and if one never does. */
export const DEFAULT_CLIENT_CONFIG: ClientConfig = {
  flushIntervalMs: 80,
  drawingFramesPerWindow: 100,
  drawingWindowSeconds: 2,
  afkInputWindowMs: 60_000,
};

/** The bounds the server enforces, mirrored so a bad payload cannot get through.

Not a second opinion about the right value — the server owns that. This only
refuses a number that would break the client outright: a zero or negative
interval is a busy loop, and a huge one is a canvas that never updates. */
const BOUNDS: Record<keyof ClientConfig, { min: number; max: number }> = {
  flushIntervalMs: { min: 10, max: 200 },
  drawingFramesPerWindow: { min: 50, max: 400 },
  drawingWindowSeconds: { min: 0.5, max: 10 },
  // A window of zero would ask somebody who is typing; one of an hour would
  // answer for somebody who left. Neither breaks the client, but both defeat
  // the check, so the same mirrored-bounds rule applies.
  afkInputWindowMs: { min: 5_000, max: 600_000 },
};

function reading(
  payload: Record<string, unknown> | undefined,
  key: keyof ClientConfig,
): number {
  const value = payload?.[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return DEFAULT_CLIENT_CONFIG[key];
  }
  const { min, max } = BOUNDS[key];
  if (value < min || value > max) return DEFAULT_CLIENT_CONFIG[key];
  return value;
}

/** The notice shape this build understands. */
export const CLIENT_CONFIG_CONTRACT_VERSION = 4;

/** Read a `client_config` notice, or `null` if it is not one this build knows.

The version is checked as a whole before any field is read, the same way the
shutdown and pause notices are. A later server could give a field a different
meaning rather than a different name — a window instead of an interval, say —
and a client that took the fields it recognised would apply half of a contract
it does not understand. Ignoring the notice leaves the cadences that have
always worked, which is the safe direction and the one every field-level
fallback below already takes. */
export function parseClientConfig(payload: unknown): ClientConfig | null {
  if (typeof payload !== "object" || payload === null) return null;
  const record = payload as Record<string, unknown>;
  if (record.contractVersion !== CLIENT_CONFIG_CONTRACT_VERSION) return null;
  return {
    flushIntervalMs: reading(record, "flushIntervalMs"),
    drawingFramesPerWindow: reading(record, "drawingFramesPerWindow"),
    drawingWindowSeconds: reading(record, "drawingWindowSeconds"),
    afkInputWindowMs: reading(record, "afkInputWindowMs"),
  };
}

let current: ClientConfig = DEFAULT_CLIENT_CONFIG;
const listeners = new Set<(config: ClientConfig) => void>();

/** The cadences in force right now. */
export function currentClientConfig(): ClientConfig {
  return current;
}

/** Adopt a notice from the server, telling everyone who is listening.

Silent when nothing moved, so a reconnect — which re-sends the same values —
does not tear down and re-arm every timer that depends on them. */
export function applyClientConfig(payload: unknown): ClientConfig {
  const next = parseClientConfig(payload);
  if (next === null) return current;
  const unchanged = (
    Object.keys(next) as (keyof ClientConfig)[]
  ).every((key) => next[key] === current[key]);
  if (unchanged) return current;
  current = next;
  listeners.forEach((listener) => listener(current));
  return current;
}

/** Subscribe to the cadences. Called immediately with what is known already. */
export function onClientConfig(
  listener: (config: ClientConfig) => void,
): () => void {
  listeners.add(listener);
  listener(current);
  return () => {
    listeners.delete(listener);
  };
}

/** Forget everything, for tests that need a clean channel. */
export function resetClientConfig(): void {
  current = DEFAULT_CLIENT_CONFIG;
  listeners.clear();
}
