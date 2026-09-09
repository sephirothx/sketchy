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

/** Where a friendship with one online player has got to.

Named for the state rather than for a control: the row acts on `add` and only
*reports* `accept` and `sent`, because a request is answered on the friends
surface (R-FRIEND-10).

Kept as a derivation over the lists rather than as flags on the row, because
the presence channel and the friend lists arrive independently and neither is
the other's source of truth. */
export type FriendAction = "add" | "accept" | "sent" | "friends" | "none";

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

/** The friends surface, in the order it is read (R-FRIEND-10).

Three groups rather than one list, because the answer each asks for is
different: an incoming request wants an answer, an outgoing one wants leaving
alone or withdrawing, and a friendship wants neither. Derived here rather than
in the component so the ordering is checkable without a browser.

Requests are newest first — a fresh ask is the one still on somebody's mind —
and friendships are alphabetical, because a friend list is scanned for a name
rather than read from the top. `localeCompare` rather than `<`, so an accented
name sorts where a reader expects it rather than after `z`. */
export interface FriendsSurface {
  incoming: FriendEntry[];
  outgoing: FriendEntry[];
  friends: FriendEntry[];
}

function newestFirst(entries: FriendEntry[]): FriendEntry[] {
  return [...entries].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export function friendsSurface(lists: FriendLists): FriendsSurface {
  return {
    incoming: newestFirst(lists.incoming),
    outgoing: newestFirst(lists.outgoing),
    friends: [...lists.friends].sort((a, b) =>
      a.displayName.localeCompare(b.displayName, undefined, { sensitivity: "base" }),
    ),
  };
}

/** Whether the surface has nothing in it at all.

One check rather than three at the call site: the empty state is about the
whole surface, and a reader with two pending requests and no friends is not
looking at an empty screen. */
export function friendsSurfaceIsEmpty(surface: FriendsSurface): boolean {
  return (
    surface.incoming.length === 0 &&
    surface.outgoing.length === 0 &&
    surface.friends.length === 0
  );
}

/** What a profile page may offer the viewer about its subject.

The same four answers `friendActionFor` gives a lobby row, decided from the
same lists — but from a profile there is no presence to consult, and the
subject may be the viewer themselves, a guest, or somebody not signed in at
all. Kept beside the lobby's version rather than shared with it, because the
inputs genuinely differ: one has an `OnlinePlayer`, the other has whatever the
profile endpoint returned.

`sent` is deliberately still offered as a state rather than hidden. A request
you sent is a thing you may want to withdraw, and a profile is where somebody
goes to look at one person. */
export function profileFriendActionFor(
  subject: { userId: string; isAnonymous: boolean } | null,
  lists: FriendLists,
  viewer: { userId: string; isAnonymous: boolean } | null,
): FriendAction {
  if (!subject || !viewer) return "none";
  // Both sides must be registered accounts (R-FRIEND-03), and nobody is their
  // own friend.
  if (viewer.isAnonymous || subject.isAnonymous) return "none";
  if (subject.userId === viewer.userId) return "none";
  if (lists.friends.some((entry) => entry.userId === subject.userId)) return "friends";
  if (lists.incoming.some((entry) => entry.userId === subject.userId)) return "accept";
  if (lists.outgoing.some((entry) => entry.userId === subject.userId)) return "sent";
  return "add";
}

/** Somebody the viewer finished a game with lately, offered as a friend.

The endpoint deliberately says nothing about friendships or refusals, because
an absence from its list would be readable and a decline must not be
(R-FRIEND-04). So the filtering happens here, over lists the viewer can
already see: an existing friend and an open request in either direction are
dropped, and a refusal is not — its row simply does nothing when pressed. */
export interface RecentPlayer {
  userId: string;
  displayName: string;
  nameColor: string | null;
  avatarUrl: string | null;
  lastPlayedAt: string;
}

export function parseRecentPlayers(payload: unknown): RecentPlayer[] {
  if (!payload || typeof payload !== "object") return [];
  const rows = (payload as Record<string, unknown>).players;
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const row = value as Record<string, unknown>;
    if (typeof row.userId !== "string" || !row.userId) return [];
    if (typeof row.displayName !== "string") return [];
    return [
      {
        userId: row.userId,
        displayName: row.displayName,
        nameColor: typeof row.nameColor === "string" ? row.nameColor : null,
        avatarUrl: typeof row.avatarUrl === "string" ? row.avatarUrl : null,
        lastPlayedAt: typeof row.lastPlayedAt === "string" ? row.lastPlayedAt : "",
      },
    ];
  });
}

export function addableRecentPlayers(
  players: RecentPlayer[],
  lists: FriendLists,
): RecentPlayer[] {
  const known = new Set([
    ...lists.friends.map((entry) => entry.userId),
    ...lists.incoming.map((entry) => entry.userId),
    ...lists.outgoing.map((entry) => entry.userId),
  ]);
  return players.filter((player) => !known.has(player.userId));
}
