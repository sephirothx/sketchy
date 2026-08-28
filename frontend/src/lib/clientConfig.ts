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
answer that has always worked. */

export interface ClientConfig {
  flushIntervalMs: number;
  lobbyPollIntervalMs: number;
}

/** What the client uses until a server says otherwise, and if one never does. */
export const DEFAULT_CLIENT_CONFIG: ClientConfig = {
  flushIntervalMs: 40,
  lobbyPollIntervalMs: 4000,
};

/** The bounds the server enforces, mirrored so a bad payload cannot get through.

Not a second opinion about the right value — the server owns that. This only
refuses a number that would break the client outright: a zero or negative
interval is a busy loop, and a huge one is a canvas that never updates. */
const BOUNDS: Record<keyof ClientConfig, { min: number; max: number }> = {
  flushIntervalMs: { min: 10, max: 200 },
  lobbyPollIntervalMs: { min: 1000, max: 60000 },
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

/** Read a `client_config` notice, keeping every field that makes sense. */
export function parseClientConfig(payload: unknown): ClientConfig {
  const record =
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>)
      : undefined;
  return {
    flushIntervalMs: reading(record, "flushIntervalMs"),
    lobbyPollIntervalMs: reading(record, "lobbyPollIntervalMs"),
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
