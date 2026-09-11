/** Friends: the shapes the lobby reads them through, and the rules over them.

Deliberately free of runtime imports. `frontend/tests` runs on bare
`node:test` with no bundler, so a module that pulls in `api.ts` cannot be
imported by a test at all — which is how the logic worth checking ends up
reachable only by the Playwright suite. The calls themselves live in
`friendsApi.ts`. */

import type { OnlinePlayer } from "./lobbyPresence";
import { ui } from "../content/ui/index.ts";

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
  /** Requests this account sent that were accepted and that nobody has told
      them about yet. Read off the row rather than derived from the lists
      moving: a client that was reloading when the answer came has no earlier
      read to compare against, and being accepted is not something anybody
      should have to be looking at the right moment to learn (R-FRIEND-14). */
  announce: FriendEntry[];
}

export const NO_FRIENDS: FriendLists = {
  friends: [],
  incoming: [],
  outgoing: [],
  announce: [],
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
    announce: parseList(body.announce),
  };
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
        : ui.friends.aFriend,
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

/** Where a friendship between the viewer and one other account has got to.

Four states, of which only `add` and `accept` are things to press. Derived
from the lists rather than carried as a flag on a row, because the lists and
whatever is being drawn beside them arrive independently and neither is the
other's source of truth. */
export type FriendAction = "add" | "accept" | "sent" | "friends" | "none";

/** What a profile page may offer the viewer about its subject.

What a page about one person may offer about them, in full: the ask, an
incoming request to accept, and one already sent. A lobby row offers only the
first of those (`lobbyRowMayOfferFriendship`), because a row that comes and
goes with presence is the wrong place to read a request from (R-FRIEND-11).

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

/** Whether a lobby row may offer to ask for a friendship.

Deliberately narrower than `profileFriendActionFor`, and deliberately blind to
requests. R-FRIEND-11 keeps friendship *state* off the presence list - a row
comes and goes as tabs open and close, so a request reported there could be
answered only while its sender happened to still be standing in the lobby - and
that reasoning is untouched by a menu. What a menu does change is the offer: an
action taken once and finished is not state to be read, and a row that already
knows whether somebody is a friend (it offers *Join* on the strength of it) can
offer to become one.

So this consults `friends` and nothing else. An outgoing request already sent,
or an incoming one waiting, leaves the offer exactly where it was: pressing it
is what the server resolves - a duplicate changes nothing, and asking somebody
who has asked you accepts them. Neither outcome needs the row to have said
anything about a request first. */
export function lobbyRowMayOfferFriendship(
  subject: { userId: string; isAnonymous: boolean } | null,
  lists: FriendLists,
  viewer: { userId: string; isAnonymous: boolean } | null,
): boolean {
  if (!subject || !viewer) return false;
  // Both sides must be registered accounts (R-FRIEND-03), and nobody is their
  // own friend.
  if (viewer.isAnonymous || subject.isAnonymous) return false;
  if (subject.userId === viewer.userId) return false;
  return !lists.friends.some((entry) => entry.userId === subject.userId);
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

/** What moved between two readings of the lists.

`friends_changed` is deliberately contentless — one event covers a request
arriving and one being answered, and the listing endpoint is the truth either
way. So what happened is worked out here, by comparing the lists before and
after the refetch it triggers. No wire change, and it is the only way to tell
"somebody asked" from "somebody said yes", which was silent before.

**A vanished outgoing request is not reported, and that is the whole point.**
An outgoing row disappears when it is declined, and naming that would go
further than R-FRIEND-05 allows: the list not pretending the row is still
pending is one thing, announcing the refusal is another.

`accepted` requires the entry to have been *outgoing* before. A friendship the
reader made themselves — by accepting a request, or by asking somebody who had
already asked them — also appears in `friends` for the first time, and telling
somebody what they just did is noise. */
export interface FriendListChanges {
  /** Requests that were not waiting a moment ago. */
  arrived: FriendEntry[];
  /** Requests this account sent that have since been said yes to. */
  accepted: FriendEntry[];
}

export const NO_FRIEND_CHANGES: FriendListChanges = { arrived: [], accepted: [] };

function idsOf(entries: FriendEntry[]): Set<string> {
  return new Set(entries.map((entry) => entry.userId));
}

/** What is owed telling, and what the diff can still add.

`accepted` comes from the server: it is a fact on the friendship rather than
a difference between two reads, so a reader who was not present for the move
still gets it. `arrived` stays a diff - an incoming request that goes
unannounced is still sitting in the list with a badge over it, while an
acceptance leaves no trace at all (R-FRIEND-14). */
export function friendListChanges(
  before: FriendLists,
  after: FriendLists,
): FriendListChanges {
  const knewIncoming = idsOf(before.incoming);
  return {
    arrived: after.incoming.filter((entry) => !knewIncoming.has(entry.userId)),
    // Defensive: a payload without the field at all is an older server, and
    // an acceptance told late beats one that throws.
    accepted: after.announce ?? [],
  };
}

/** How many requests are waiting for an answer.

The badge's number, and the only count worth showing: a friendship needs
nothing, and a request this account sent is waiting on somebody else. */
export function waitingRequestCount(lists: FriendLists): number {
  return lists.incoming.length;
}


/** Whether a failed friend-list read is the guest refusal rather than a fault.

The two have to be told apart, because only one of them is an answer. A guest
is refused, and that refusal *is* their list: they have none, and every
control that would use one is hidden. A timeout, a dropped connection or a 500
says nothing about who this account is friends with, and treating it as "no
friends, and we know it" is worse than saying nothing — the lists empty on
screen, a profile starts deriving *Add friend* from a state that is not true,
and the next successful read diffs against the false empty list and announces
every request that was already waiting.

Matched on the name the server's own header put there, not on the status: a
403 is not a reason. A suspended account is refused with one too, before this
endpoint runs at all, and reading that as "no friends" wipes a real account's
lists off the screen and leaves the next good read announcing everything on
them as new.

Duck-typed on the name rather than importing `AccountRequiredError`, so this
stays in a module with no runtime imports and can be checked without a
bundler. */
export function isNoFriendListRefusal(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  return (error as { name?: unknown }).name === "AccountRequiredError";
}
