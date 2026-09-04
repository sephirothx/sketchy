/** Friends: the shapes the lobby reads them through, and the rules over them.

Deliberately free of runtime imports. `frontend/tests` runs on bare
`node:test` with no bundler, so a module that pulls in `api.ts` cannot be
imported by a test at all — which is how the logic worth checking ends up
reachable only by the Playwright suite. The calls themselves live in
`friendsApi.ts`. */

import type { OnlinePlayer } from "./lobbyPresence";

/** Mirrors `FriendshipState` in `backend/app/domain_values.py`.

`declined` never reaches the client: the listing endpoint leaves refusals out,
because neither side is owed a standing reminder of one. */
export type FriendshipStatus = "pending" | "accepted";

export interface FriendEntry {
  userId: string;
  displayName: string;
  nameColor: string | null;
  avatarUrl: string | null;
  isAnonymous: boolean;
  status: FriendshipStatus;
  /** Which of the two asked. The server sends a boolean, not an id. */
  requestedByMe: boolean;
  createdAt: string;
  respondedAt: string | null;
}

export interface FriendLists {
  friends: FriendEntry[];
  incoming: FriendEntry[];
  outgoing: FriendEntry[];
}

export const NO_FRIENDS: FriendLists = {
  friends: [],
  incoming: [],
  outgoing: [],
};

function parseEntry(value: unknown): FriendEntry | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.userId !== "string" || !row.userId) return null;
  if (typeof row.displayName !== "string") return null;
  if (row.status !== "pending" && row.status !== "accepted") return null;
  return {
    userId: row.userId,
    displayName: row.displayName,
    nameColor: typeof row.nameColor === "string" ? row.nameColor : null,
    avatarUrl: typeof row.avatarUrl === "string" ? row.avatarUrl : null,
    isAnonymous: row.isAnonymous === true,
    status: row.status,
    requestedByMe: row.requestedByMe === true,
    createdAt: typeof row.createdAt === "string" ? row.createdAt : "",
    respondedAt: typeof row.respondedAt === "string" ? row.respondedAt : null,
  };
}

function parseList(value: unknown): FriendEntry[] {
  if (!Array.isArray(value)) return [];
  return value.map(parseEntry).filter((row): row is FriendEntry => row !== null);
}

export function parseFriendLists(payload: unknown): FriendLists {
  if (!payload || typeof payload !== "object") return NO_FRIENDS;
  const body = payload as Record<string, unknown>;
  return {
    friends: parseList(body.friends),
    incoming: parseList(body.incoming),
    outgoing: parseList(body.outgoing),
  };
}

/** What the lobby offers on one online player's row.

Kept as a derivation over the lists rather than as flags on the row, because
the presence channel and the friend lists arrive independently and neither is
the other's source of truth. */
export type FriendAction = "add" | "accept" | "sent" | "none";

export function friendActionFor(
  player: OnlinePlayer,
  lists: FriendLists,
  myUserId: string | null,
): FriendAction {
  // Guests have no durable identity to be friends with, and the server
  // refuses one anyway — so the row does not offer something that cannot work.
  if (player.isAnonymous) return "none";
  if (!myUserId || player.userId === myUserId) return "none";
  if (lists.friends.some((entry) => entry.userId === player.userId)) return "none";
  if (lists.incoming.some((entry) => entry.userId === player.userId)) return "accept";
  if (lists.outgoing.some((entry) => entry.userId === player.userId)) return "sent";
  return "add";
}

export function isFriend(lists: FriendLists, userId: string): boolean {
  return lists.friends.some((entry) => entry.userId === userId);
}

/** The online list, with friends first.

A term in front of the comparator the server sorts by, rather than a change to
it: the rest of the order still decides among friends, and among everyone
else. So the two ends still agree on everything below this line, which is what
`fixtures/lobby_presence_v1.json` pins. */
export function withFriendsFirst(
  players: OnlinePlayer[],
  lists: FriendLists,
): OnlinePlayer[] {
  const friendIds = new Set(lists.friends.map((entry) => entry.userId));
  if (friendIds.size === 0) return players;
  const friends: OnlinePlayer[] = [];
  const rest: OnlinePlayer[] = [];
  for (const player of players) {
    (friendIds.has(player.userId) ? friends : rest).push(player);
  }
  return [...friends, ...rest];
}

export interface FriendInvite {
  fromUserId: string;
  displayName: string;
  inviteToken: string;
  /** Seconds the invitation is good for, from when it arrived. */
  expiresIn: number;
}

export function parseFriendInvite(payload: unknown): FriendInvite | null {
  if (!payload || typeof payload !== "object") return null;
  const body = payload as Record<string, unknown>;
  if (typeof body.fromUserId !== "string" || !body.fromUserId) return null;
  if (typeof body.inviteToken !== "string" || !body.inviteToken) return null;
  const expiresIn =
    typeof body.expiresIn === "number" && Number.isFinite(body.expiresIn)
      ? body.expiresIn
      : 0;
  if (expiresIn <= 0) return null;
  return {
    fromUserId: body.fromUserId,
    displayName:
      typeof body.displayName === "string" && body.displayName
        ? body.displayName
        : "A friend",
    inviteToken: body.inviteToken,
    expiresIn,
  };
}
