/** The public room list, as the lobby channel delivers it.

The same shape `lobbyPresence.ts` uses, and for the same reasons: a snapshot to
start from, deltas after it, and a monotonic revision so a client that missed
one can tell and ask for a fresh start rather than patching around the gap.

Pure, and free of runtime imports, so `frontend/tests` can reach it — which is
the lesson #450 filed about the polling version of this. That lived inside the
lobby component and could only be exercised by rendering it, so the ETag bug in
#449 got as far as human review with nothing able to catch it. */

import type { RoomSummary } from "../types";

export interface RoomsState {
  /** The revision the list below is at. Zero before the first message. */
  revision: number;
  rooms: RoomSummary[];
  /** True once a baseline has arrived, so "none" can be told from "not yet". */
  loaded: boolean;
  /** Set when a delta arrived out of order. The hook re-subscribes. */
  needsResync: boolean;
  /** The rooms are the last ones a live server named, but the sequence they
      belonged to is gone - so they may be drawn and must not be patched. */
  stale: boolean;
}

export const NO_ROOMS: RoomsState = {
  revision: 0,
  rooms: [],
  loaded: false,
  needsResync: false,
  stale: false,
};

/** Keep the list, abandon the sequence it belonged to.

A reconnect is a new socket in a new server, so every revision this client
holds is meaningless - but the *rooms* are not. They are public, they were true
a moment ago, and a poll would have gone on showing them for up to four
seconds. Blanking the lobby on a transport bounce would be a regression in what
the reader sees for the sake of an internal counter.

So the rooms stay on screen and no delta is applied to them: only a snapshot
clears `stale`, and the hook asks for one the moment it reconnects.

Presence deliberately does the opposite and empties. A room that closed while
we were away is a card that fails when clicked; a *person* shown as online who
is not is a friend request sent into silence, so that list is only ever drawn
from something the server said in this connection. */
export function markRoomsStale(state: RoomsState): RoomsState {
  if (!state.loaded) return NO_ROOMS;
  return { ...state, revision: 0, needsResync: false, stale: true };
}

/** One room, or null if the server sent something this build cannot place.

Only the id is required. Every other field is the server's to describe, and a
card missing an optional is a better failure than a lobby that drops the room. */
function parseRoom(value: unknown): RoomSummary | null {
  if (!value || typeof value !== "object") return null;
  const room = value as Record<string, unknown>;
  if (typeof room.id !== "string" || !room.id) return null;
  return room as unknown as RoomSummary;
}

function parseRooms(value: unknown): RoomSummary[] {
  if (!Array.isArray(value)) return [];
  return value.map(parseRoom).filter((room): room is RoomSummary => room !== null);
}

function parseRevision(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

/** Replace the list wholesale: the answer to `watch_lobby`, and every resync.

Never backwards. The socket joins the channel before its acknowledgement is
built, so a delta can already be in flight when the baseline is stamped, and a
resync asked for twice can be answered out of order. Applying the older of two
snapshots would put the client behind a delta it has already applied and leave
it there, because nothing after that would look like a gap. */
export function applyRoomsSnapshot(
  state: RoomsState,
  rooms: unknown,
  revision: unknown,
): RoomsState {
  const at = parseRevision(revision);
  if (at === null) return NO_ROOMS;
  // A stale list holds no usable revision, so anything the server says wins.
  if (state.loaded && !state.stale && at < state.revision) return state;
  return {
    revision: at,
    rooms: parseRooms(rooms),
    loaded: true,
    needsResync: false,
    stale: false,
  };
}

/** Apply one delta, or ask for a resync if it is not the next one. */
export function applyRoomsDelta(state: RoomsState, payload: unknown): RoomsState {
  if (!payload || typeof payload !== "object") return state;
  // A list whose sequence ended cannot be patched back into agreement with
  // the server. The snapshot on the way replaces it wholesale.
  if (state.stale) return state;
  // Nor can a list that never began. `enter_room` runs before the
  // acknowledgement is built, so the first delta can arrive before the
  // baseline it applies to - and patching an empty list would leave the lobby
  // showing only the rooms that happened to move while `loaded` claimed that
  // was the whole list. The acknowledgement is already on its way.
  if (!state.loaded) return state;
  const message = payload as Record<string, unknown>;
  const revision = parseRevision(message.revision);
  if (revision === null) return state;
  // Already seen, or from before a resync landed.
  if (revision <= state.revision) return state;
  if (revision !== state.revision + 1) {
    // Something was missed, so the list stops being trustworthy. Abandoned
    // rather than patched: the hook re-subscribes and the acknowledgement
    // replaces it.
    return { ...state, needsResync: true };
  }

  const byId = new Map(state.rooms.map((room) => [room.id, room]));
  for (const room of parseRooms(message.opened)) byId.set(room.id, room);
  for (const room of parseRooms(message.changed)) byId.set(room.id, room);
  if (Array.isArray(message.closed)) {
    for (const id of message.closed) {
      if (typeof id === "string") byId.delete(id);
    }
  }
  return {
    revision,
    rooms: [...byId.values()],
    loaded: true,
    needsResync: false,
    stale: false,
  };
}
