/** The friends endpoints, and nothing else.

Split from `friends.ts` so the rules over these shapes stay importable by a
test runner with no bundler behind it. */

import { apiRequest } from "./api";
import {
  parseFriendLists,
  parseRecentPlayers,
  type FriendLists,
  type RecentPlayer,
} from "./friends";

export async function listFriends(): Promise<FriendLists> {
  return parseFriendLists(await apiRequest("/api/users/me/friends"));
}

export function requestFriend(userId: string): Promise<{ status: string }> {
  return apiRequest("/api/users/me/friends", {
    method: "POST",
    body: { userId },
  });
}

export function acceptFriend(userId: string): Promise<{ status: string }> {
  return apiRequest(`/api/users/me/friends/${userId}/accept`, {
    method: "POST",
  });
}

/** Decline, cancel, or unfriend — the server decides which this is. */
/** Record that the asker was told, naming exactly what the message said.

Sent after the message is shown. Recording first loses the news whenever the
render does not happen, and recording everything outstanding swallows an
acceptance that landed in between; the failure this leaves is being told
twice (R-FRIEND-14). */
export function announcedFriendships(
  userIds: string[],
): Promise<{ ok: boolean; announced: number }> {
  return apiRequest("/api/users/me/friends/announced", {
    method: "POST",
    body: { userIds },
  });
}

export function removeFriend(userId: string): Promise<void> {
  return apiRequest(`/api/users/me/friends/${userId}`, { method: "DELETE" });
}

/** Registered accounts the caller finished a game with lately.

Separate from the friend lists, and refetched beside them rather than folded
into `/friends`: the two answer different questions, and this one costs a join
over game history that the lists should not have to wait for. */
export async function listRecentPlayers(): Promise<RecentPlayer[]> {
  return parseRecentPlayers(await apiRequest("/api/users/me/recent-players"));
}
