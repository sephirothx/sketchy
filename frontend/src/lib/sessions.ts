import { apiRequest } from "./api";

export interface AccountSession {
  id: string;
  deviceLabel: string;
  createdAt: string;
  lastUsedAt: string;
  expiresAt: string;
  current: boolean;
}

export function fetchAccountSessions(): Promise<{ sessions: AccountSession[] }> {
  return apiRequest("/api/auth/sessions");
}

export function revokeAccountSession(sessionId: string): Promise<{ ok: boolean }> {
  return apiRequest(`/api/auth/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export function logoutEverywhere(): Promise<{ ok: boolean; revoked: number }> {
  return apiRequest("/api/auth/logout-all", { method: "POST" });
}
