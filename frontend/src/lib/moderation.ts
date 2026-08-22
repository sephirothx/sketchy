import { apiRequest } from "./api.ts";
import type { ModerationState } from "../types";

export function canCastModerationVote(
  moderation: ModerationState,
  playerId: string | null | undefined,
): boolean {
  return Boolean(playerId && moderation.eligibleVoterIds.includes(playerId));
}

export function eligibleModerationVotes(
  moderation: ModerationState,
  votes: string[] | undefined,
): string[] {
  const eligibleVoterIds = new Set(moderation.eligibleVoterIds);
  return (votes ?? []).filter((playerId) => eligibleVoterIds.has(playerId));
}

export type ReportReason =
  | "harassment"
  | "offensive_drawing"
  | "inappropriate_name"
  | "cheating"
  | "spam";
export type ReportStatus = "pending" | "resolved" | "dismissed";

export interface PlayerReport {
  id: string;
  reporterUserId: string | null;
  reportedUserId: string | null;
  gameId: string | null;
  turnId: string | null;
  reason: ReportReason;
  details: string;
  contextSnapshot: Record<string, unknown>;
  status: ReportStatus;
  reviewedByUserId: string | null;
  resolutionNote: string | null;
  createdAt: string;
  updatedAt: string;
  reviewedAt: string | null;
}

export interface UserBan {
  id: string;
  userId: string | null;
  bannedByUserId: string | null;
  reason: string;
  expiresAt: string | null;
  isActive: boolean;
  createdAt: string;
  revokedAt: string | null;
  revokedByUserId: string | null;
  revokeReason: string | null;
}

export function submitPlayerReport(input: {
  reportedUserId: string;
  gameId?: string;
  turnId?: string;
  reason: ReportReason;
  details: string;
  contextSnapshot?: Record<string, unknown>;
}): Promise<{ id: string; status: ReportStatus; createdAt: string }> {
  return apiRequest("/api/reports", { method: "POST", body: input });
}

export function listModerationReports(status?: ReportStatus): Promise<{
  reports: PlayerReport[];
}> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiRequest(`/api/moderation/reports${query}`);
}

export function reviewModerationReport(
  reportId: string,
  status: Exclude<ReportStatus, "pending">,
  note: string,
): Promise<PlayerReport> {
  return apiRequest(`/api/moderation/reports/${reportId}`, {
    method: "PATCH",
    body: { status, note },
  });
}

export function createUserBan(input: {
  userId: string;
  reason: string;
  expiresAt?: string;
}): Promise<UserBan> {
  return apiRequest("/api/moderation/bans", { method: "POST", body: input });
}

export function revokeUserBan(banId: string, reason: string): Promise<UserBan> {
  return apiRequest(`/api/moderation/bans/${banId}/revoke`, {
    method: "POST",
    body: { reason },
  });
}
