/** The friends endpoints, and nothing else.

Split from `friends.ts` so the rules over these shapes stay importable by a
test runner with no bundler behind it. */

import { apiRequest } from "./api";
import { parseFriendLists, type FriendLists } from "./friends";

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
export function removeFriend(userId: string): Promise<void> {
  return apiRequest(`/api/users/me/friends/${userId}`, { method: "DELETE" });
}
