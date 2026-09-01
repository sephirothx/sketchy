/** The lobby's online player list: the store, and the rules it applies.

Kept out of the component on purpose. `frontend/tests` runs on bare
`node:test` with no DOM, so anything reachable only by rendering is reachable
only by the Playwright suite - which is how the ETag bug in #449 got as far as
human review. Everything here is a pure function over plain objects.

The channel is a snapshot followed by deltas, and the client is deliberately
*not* authoritative about presence: every message carries a monotonic
`revision`, and one that does not follow the revision we hold means something
was missed. The answer to that is to throw the store away and ask for a fresh
snapshot, never to patch around the gap. That is what makes a delta protocol
safe here in a way it was not for room state (#493): a stale lobby row is
cosmetic, and the resync corrects it within a tick. */

export type PresenceStatus = "lobby" | "playing";

export interface OnlinePlayer {
  userId: string;
  displayName: string;
  nameColor: string | null;
  isAnonymous: boolean;
  status: PresenceStatus;
}

export interface PresenceState {
  /** The revision the list below is at. Zero before the first message. */
  revision: number;
  players: OnlinePlayer[];
  /** Everyone online, including whoever did not fit in `players`. */
  onlineCount: number;
  /** Set when a delta arrived out of order. The hook re-subscribes. */
  needsResync: boolean;
}

export const EMPTY_PRESENCE: PresenceState = {
  revision: 0,
  players: [],
  onlineCount: 0,
  needsResync: false,
};

/** The order the server sorts by, applied again after every delta.

Registered before guests, then display name case-insensitively, then the
account id so the order is total rather than dependent on insertion.

The two ends can hold this comparator identically because display names are
`[a-zA-Z0-9_-]` by the server's `NAME_PATTERN`: `toLowerCase` and Python's
`lower` are the same function over that range, and comparing by UTF-16 code
unit and by code point are the same comparison. `fixtures/lobby_presence_v1.json`
pins that they agree. */
export function comparePlayers(a: OnlinePlayer, b: OnlinePlayer): number {
  if (a.isAnonymous !== b.isAnonymous) return a.isAnonymous ? 1 : -1;
  const left = a.displayName.toLowerCase();
  const right = b.displayName.toLowerCase();
  if (left !== right) return left < right ? -1 : 1;
  if (a.userId === b.userId) return 0;
  return a.userId < b.userId ? -1 : 1;
}

function isStatus(value: unknown): value is PresenceStatus {
  return value === "lobby" || value === "playing";
}

/** One row, or null if the server sent something this build cannot read. */
export function parsePlayer(value: unknown): OnlinePlayer | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.userId !== "string" || !row.userId) return null;
  if (typeof row.displayName !== "string") return null;
  if (!isStatus(row.status)) return null;
  return {
    userId: row.userId,
    displayName: row.displayName,
    nameColor: typeof row.nameColor === "string" ? row.nameColor : null,
    isAnonymous: row.isAnonymous === true,
    status: row.status,
  };
}

function parsePlayers(value: unknown): OnlinePlayer[] {
  if (!Array.isArray(value)) return [];
  return value.map(parsePlayer).filter((row): row is OnlinePlayer => row !== null);
}

function parseCount(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : fallback;
}

function parseRevision(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

/** Replace the store wholesale. The answer to `watch_lobby`, and to a resync. */
export function applySnapshot(payload: unknown): PresenceState {
  if (!payload || typeof payload !== "object") return EMPTY_PRESENCE;
  const message = payload as Record<string, unknown>;
  const revision = parseRevision(message.revision);
  if (revision === null) return EMPTY_PRESENCE;
  const players = parsePlayers(message.players).sort(comparePlayers);
  return {
    revision,
    players,
    onlineCount: parseCount(message.onlineCount, players.length),
    needsResync: false,
  };
}

/** Apply one delta, or ask for a resync if it is not the next one.

`joined` and `changed` are upserts and `left` is a delete, so applying a
message twice changes nothing - which is what lets the acknowledgement to
`watch_lobby` carry a list fresher than the channel's own without the next
delta double-counting anything. */
export function applyDelta(
  state: PresenceState,
  payload: unknown,
): PresenceState {
  if (!payload || typeof payload !== "object") return state;
  const message = payload as Record<string, unknown>;
  const revision = parseRevision(message.revision);
  if (revision === null) return state;
  // Already seen, or from before a resync landed: nothing to do, and
  // certainly nothing to ask for.
  if (revision <= state.revision) return state;
  if (revision !== state.revision + 1) {
    // Something was missed. The store stops being trustworthy at this point,
    // so it is abandoned rather than patched - the hook re-subscribes and the
    // acknowledgement replaces it.
    return { ...state, needsResync: true };
  }

  const byId = new Map(state.players.map((player) => [player.userId, player]));
  for (const row of parsePlayers(message.joined)) byId.set(row.userId, row);
  for (const row of parsePlayers(message.changed)) byId.set(row.userId, row);
  if (Array.isArray(message.left)) {
    for (const userId of message.left) {
      if (typeof userId === "string") byId.delete(userId);
    }
  }

  const players = [...byId.values()].sort(comparePlayers);
  return {
    revision,
    players,
    onlineCount: parseCount(message.onlineCount, players.length),
    needsResync: false,
  };
}

/** "8 online", or "Showing 100 of 412" when the list did not fit.

Without the total a cap is indistinguishable from a quiet server, which is
the one reading that would make the panel actively misleading. */
export function presenceSummary(state: PresenceState): string {
  const shown = state.players.length;
  if (state.onlineCount > shown) return `Showing ${shown} of ${state.onlineCount}`;
  return `${state.onlineCount} online`;
}

/** Case-insensitive filter over what the client actually holds.

Only ever a filter of the rows already on screen - never presented as a
search of everyone online, because beyond the cap it would answer "no such
player" about somebody who is. */
export function filterPlayers(
  players: OnlinePlayer[],
  query: string,
): OnlinePlayer[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return players;
  return players.filter((player) =>
    player.displayName.toLowerCase().includes(needle),
  );
}
