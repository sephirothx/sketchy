import { apiRequest } from "./api";

export interface UserBlock {
  id: string;
  userId: string;
  username: string | null;
  displayName: string;
  isAnonymous: boolean;
  createdAt: string;
}

export function listUserBlocks(): Promise<{ blocks: UserBlock[] }> {
  return apiRequest("/api/users/me/blocks");
}

export function blockUser(userId: string): Promise<UserBlock> {
  return apiRequest("/api/users/me/blocks", {
    method: "POST",
    body: { userId },
  });
}

export function unblockUser(userId: string): Promise<void> {
  return apiRequest(`/api/users/me/blocks/${userId}`, { method: "DELETE" });
}
