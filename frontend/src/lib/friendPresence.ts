/** Which friends are online, asked for by this account alone (#873, #878).

The lobby's public list is capped at a hundred and sorted by name, so a friend
past the cut was neither shown online nor offered an invitation; and the
waiting room joined the whole lobby channel to read its handful of friends.
Instead the client polls `friends_online`, which answers
`[[userId, status], …]` uncapped.

Free of runtime imports, like `friends.ts`, so `node:test` can reach it. */

import type { FriendLists } from "./friends";
import type { OnlinePlayer, PresenceStatus } from "./lobbyPresence";

/** Friend account id to what they are doing; absent means offline. */
export type FriendPresenceMap = Readonly<Record<string, PresenceStatus>>;

export const NO_FRIENDS_ONLINE: FriendPresenceMap = Object.freeze({});

/** How often a surface showing friends asks again while the tab is visible.

A friend's row can be this stale. That is cheap to be wrong about: an
invitation is checked by the server when it is sent, so the worst case is one
refused invite. Every ask after a connection's first is answered from memory. */
export const FRIENDS_POLL_MS = 15_000;

function isStatus(value: unknown): value is PresenceStatus {
  return value === "lobby" || value === "playing";
}

/** The `friends` of a `friends_online` answer; rows it cannot read are skipped. */
export function parseFriendsOnline(answer: unknown): FriendPresenceMap {
  if (!answer || typeof answer !== "object") return NO_FRIENDS_ONLINE;
  const rows = (answer as { friends?: unknown }).friends;
  if (!Array.isArray(rows)) return NO_FRIENDS_ONLINE;
  const online: Record<string, PresenceStatus> = {};
  for (const row of rows) {
    if (Array.isArray(row) && typeof row[0] === "string" && isStatus(row[1])) {
      online[row[0]] = row[1];
    }
  }
  return online;
}

/** The lobby's rows plus every online friend the capped list left out.

A friend is drawn from the friends list's own row, which carries everything a
presence row does, with the status the server told this account. */
export function withOnlineFriends(
  players: OnlinePlayer[],
  lists: FriendLists,
  online: FriendPresenceMap,
): OnlinePlayer[] {
  const shown = new Set(players.map((player) => player.userId));
  const missing: OnlinePlayer[] = [];
  for (const friend of lists.friends) {
    const status = online[friend.userId];
    if (status === undefined || shown.has(friend.userId)) continue;
    missing.push({
      userId: friend.userId,
      displayName: friend.displayName,
      nameColor: friend.nameColor,
      avatarUrl: friend.avatarUrl,
      isAnonymous: friend.isAnonymous,
      status,
    });
  }
  return missing.length === 0 ? players : [...players, ...missing];
}

/** Friends an invitation can reach: online and not already in a game. */
export function invitableFriends(lists: FriendLists, online: FriendPresenceMap) {
  return lists.friends.filter((friend) => online[friend.userId] === "lobby");
}
