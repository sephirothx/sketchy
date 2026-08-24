import { apiRequest } from "./api.ts";
import { emitWithAck } from "./socket.ts";
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

export interface PlayerReportMessageEvidence {
  sourceMessageId: string;
  sourceAvailable: boolean;
  gameId: string | null;
  turnId: string | null;
  senderUserId: string | null;
  senderDisplayName: string;
  senderNameColor: string | null;
  senderWasAnonymous: boolean;
  messageKind: "chat" | "wrong_guess" | "correct_guess";
  audience: "room" | "prompt_aware";
  nearMissKind: "close" | "partial" | null;
  text: string;
  messageCreatedAt: string;
  copiedAt: string;
}

export interface PlayerReport {
  id: string;
  reporterUserId: string | null;
  reportedUserId: string | null;
  gameId: string | null;
  turnId: string | null;
  reason: ReportReason;
  details: string;
  contextSnapshot: Record<string, unknown>;
  messageEvidence: PlayerReportMessageEvidence[];
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

/** Report somebody in the room you are both in.

Addressed by room seat, not by account: the room's payloads deliberately carry
no account ids, and filing a complaint is not a reason to learn one. The server
resolves the seat and gathers the chat evidence itself, so nothing here has to
be trusted. */
export function reportPlayerInRoom(input: {
  targetPlayerId: string;
  reason: ReportReason;
  details: string;
}): Promise<{ ok: boolean; id?: string; evidenceCount?: number; error?: string }> {
  return emitWithAck("report_player", input);
}

export function submitPlayerReport(input: {
  reportedUserId: string;
  gameId?: string;
  turnId?: string;
  reason: ReportReason;
  details: string;
  messageIds?: string[];
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

export interface PromptContentReport {
  id: string;
  reporterUserId: string | null;
  reportedOwnerUserId: string | null;
  promptListId: string | null;
  promptVersionId: string | null;
  targetType: "list" | "prompt";
  listName: string | null;
  prompt: string | null;
  reason: string;
  details: string;
  status: ReportStatus;
  reviewedByUserId: string | null;
  resolutionNote: string | null;
  moderationState: "active" | "hidden" | null;
  createdAt: string;
  updatedAt: string;
  reviewedAt: string | null;
}

export function listPromptContentReports(status?: ReportStatus): Promise<{
  reports: PromptContentReport[];
}> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiRequest(`/api/moderation/prompt-content-reports${query}`);
}

/** Resolve or dismiss a content report.

`moderationState` is what actually hides the reported list or prompt; a report
resolved without it is a decision recorded and nothing acted on. */
export function reviewPromptContentReport(
  reportId: string,
  status: Exclude<ReportStatus, "pending">,
  note: string,
  moderationState?: "active" | "hidden",
): Promise<PromptContentReport> {
  return apiRequest(`/api/moderation/prompt-content-reports/${reportId}`, {
    method: "PATCH",
    body: { status, note, ...(moderationState ? { moderationState } : {}) },
  });
}
