import { apiRequest } from "./api";

export interface AccountSession {
  id: string;
  deviceLabel: string;
  createdAt: string;
  lastUsedAt: string;
  expiresAt: string;
  /**
   * When silence alone ends this device's session — ninety days after it was
   * last used, or a day for staff. Usually much sooner than `expiresAt`, so
   * it is the date worth showing.
   */
  idleExpiresAt: string | null;
  /**
   * Set when this session was last used from a browser it was not issued to.
   * Deliberately just a time: the server keeps a hash of the address and
   * could not say where even if it wanted to.
   */
  anomalyAt: string | null;
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
