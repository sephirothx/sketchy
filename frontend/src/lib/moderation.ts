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
  | "spam"
  | "inappropriate_avatar";
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
  /** `cited` is what the report is about; `context` is what was said around
      it, by anyone, chosen by the server. Both in the order they were said. */
  role: "cited" | "context";
  text: string;
  messageCreatedAt: string;
  copiedAt: string;
}

/** The reported player's standing, as a moderator weighs the case. */
export interface ReportedPlayerContext {
  displayName: string;
  /** The picture the report may be about, so it can be judged from the queue. */
  avatarUrl?: string | null;
  registered: boolean;
  createdAt: string;
  priorReports: number;
  priorWarnings: number;
  activeSuspension: boolean;
}

export interface PlayerReport {
  id: string;
  reporterUserId: string | null;
  reportedUserId: string | null;
  /** Null when the account is gone. */
  reportedPlayer: ReportedPlayerContext | null;
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
  /** Null once the account has been anonymised - the suspension outlives the
      name, and a moderator sees that rather than a blank. */
  displayName: string | null;
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

/**
 * Take down the picture a report is about and block re-uploads for a while.
 * Reached through the report rather than the account (R-MOD-02).
 */
export function removeReportedAvatar(reportId: string): Promise<{ ok: boolean; removed: boolean }> {
  return apiRequest(`/api/moderation/reports/${reportId}/remove-avatar`, { method: "POST" });
}

export function createUserBan(input: {
  userId: string;
  reason: string;
  /** The report this was decided from, when it came from one. */
  reportId?: string;
  expiresAt?: string;
}): Promise<UserBan> {
  return apiRequest("/api/moderation/bans", { method: "POST", body: input });
}

/** A moderator warning waiting to be shown to its player. */
export interface PendingWarning {
  id: string;
  reason: string;
  createdAt: string;
  /** The reported messages behind it - the player's own words. */
  messages: { text: string; at: string | null }[];
}

export function createUserWarning(input: {
  userId: string;
  reason: string;
  /** The report this was decided from, when it came from one. */
  reportId?: string;
}): Promise<{ id: string; userId: string; reason: string; createdAt: string }> {
  return apiRequest("/api/moderation/warnings", { method: "POST", body: input });
}

export function fetchPendingWarning(): Promise<{ warning: PendingWarning | null }> {
  return apiRequest("/api/warnings/pending");
}

export function acknowledgeWarning(warningId: string): Promise<{ ok: boolean }> {
  return apiRequest(`/api/warnings/${warningId}/acknowledge`, { method: "POST" });
}

export function listUserBans(active?: boolean): Promise<{ bans: UserBan[] }> {
  const query = active === undefined ? "" : `?active=${active}`;
  return apiRequest(`/api/moderation/bans${query}`);
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

/** How long a suspension lasts. Permanent is deliberately not the default: most
misbehaviour is somebody having a bad evening, and a moderator should have to
choose forever rather than arrive at it by not choosing. */
export const SUSPENSION_DURATIONS: { value: string; label: string; hours: number | null }[] = [
  { value: "24h", label: "24 hours", hours: 24 },
  { value: "7d", label: "7 days", hours: 24 * 7 },
  { value: "30d", label: "30 days", hours: 24 * 30 },
  { value: "forever", label: "No end date", hours: null },
];

/** The absolute moment a suspension ends, or undefined for permanent.

Computed here rather than sent as a duration because the server stores an
instant: a request that took a minute to arrive should not shorten the ban by a
minute, and the API already takes expiresAt. */
export function suspensionExpiry(
  choice: string,
  now: Date = new Date(),
): string | undefined {
  const option = SUSPENSION_DURATIONS.find((entry) => entry.value === choice);
  if (!option || option.hours === null) return undefined;
  return new Date(now.getTime() + option.hours * 3600 * 1000).toISOString();
}


/** Where reports are read and acted on.

The API and its client have existed since #340; nothing called them, so every
report submitted so far has been written to a queue nobody could open. This is
the queue.

Reviewing is deliberately two decisions, not one. Resolving a content report
records that it was looked at; hiding the list or prompt is what acts on it,
and a moderator should have to mean both. */
