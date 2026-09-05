import { apiBinaryRequest, apiRequest } from "./api.ts";
import { emitWithAck } from "./socket.ts";
import type { GamePhase, ModerationState } from "../types";

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
/** What was done about a case, in one word. Player reports close as
    dismissed, warned, suspended or a plain resolved; content reports as
    dismissed, hidden, left_up or resolved. Pending until then. */
export type ReportOutcome =
  | "pending"
  | "dismissed"
  | "resolved"
  | "warned"
  | "suspended"
  | "hidden"
  | "left_up";

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

/** The canvas as it stood when the report was sent, by its metadata. The
    bytes come from `fetchReportDrawing`, in the wire format a live canvas uses. */
export interface PlayerReportDrawing {
  turnId: string;
  roundNumber: number;
  /** What the drawer was asked to draw - server-held, so it may be read as fact. */
  prompt: string;
  actionCount: number;
  byteSize: number;
  capturedAt: string;
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
  /** Null unless the reporter asked for the drawing and the reported seat was
      the one drawing at the time. */
  drawing: PlayerReportDrawing | null;
  status: ReportStatus;
  outcome: ReportOutcome;
  reviewedByUserId: string | null;
  /** The reviewer's name, resolved when the case is read; null until decided
      or once the account is gone. */
  reviewedBy: string | null;
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

/** Whether a report about this seat can carry the drawing on the canvas.

Only the drawer's own work is worth attaching, and only while the canvas still
shows it: during the drawing and on the results screen that follows. The
server applies the same rule to what it actually copies, so this decides what
is offered and never what is sent. */
export function canAttachDrawing(
  phase: GamePhase,
  drawerId: string | null | undefined,
  targetPlayerId: string,
): boolean {
  if (phase !== "drawing" && phase !== "turn_results") return false;
  return Boolean(drawerId) && drawerId === targetPlayerId;
}

/** Report somebody in the room you are both in.

Addressed by room seat, not by account: the room's payloads deliberately carry
no account ids, and filing a complaint is not a reason to learn one. The server
resolves the seat and gathers the chat evidence itself, so nothing here has to
be trusted. `includeDrawing` asks for the canvas to be copied too; the server
takes it from the room's own state, and only if that seat is the one drawing. */
export function reportPlayerInRoom(input: {
  targetPlayerId: string;
  reason: ReportReason;
  details: string;
  includeDrawing?: boolean;
}): Promise<{
  ok: boolean;
  id?: string;
  evidenceCount?: number;
  drawingAttached?: boolean;
  error?: string;
}> {
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

/** The drawing a report carries, in the wire format a live canvas uses. */
export function fetchReportDrawing(reportId: string): Promise<ArrayBuffer> {
  return apiBinaryRequest(`/api/moderation/reports/${reportId}/drawing`);
}

/** How many closed cases one page of the queue shows. */
export const CLOSED_CASES_PAGE_SIZE = 25;

/** Decided player and content reports as one stream, newest decision first.

Paged by the server rather than merged here, because closed cases accumulate
for as long as the service runs and the newest are the ones worth reaching. */
export function listClosedCases(input: { limit?: number; offset?: number } = {}): Promise<{
  players: PlayerReport[];
  content: PromptContentReport[];
  hasMore: boolean;
}> {
  const limit = input.limit ?? CLOSED_CASES_PAGE_SIZE;
  const offset = input.offset ?? 0;
  return apiRequest(`/api/moderation/closed-cases?limit=${limit}&offset=${offset}`);
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
  /** The drawing the report carried, if one did - the player's own work. */
  drawing: PlayerReportDrawing | null;
}

/** The drawing behind the caller's own warning. */
export function fetchWarningDrawing(warningId: string): Promise<ArrayBuffer> {
  return apiBinaryRequest(`/api/warnings/${warningId}/drawing`);
}

/** The drawing behind the caller's own suspension, reachable while suspended. */
export function fetchSuspensionDrawing(): Promise<ArrayBuffer> {
  return apiBinaryRequest("/api/suspension/drawing");
}

/** Keep only a payload shaped like a drawing's metadata. */
export function reportedDrawing(value: unknown): PlayerReportDrawing | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.prompt !== "string" || typeof row.turnId !== "string") return null;
  return {
    turnId: row.turnId,
    roundNumber: typeof row.roundNumber === "number" ? row.roundNumber : 0,
    prompt: row.prompt,
    actionCount: typeof row.actionCount === "number" ? row.actionCount : 0,
    byteSize: typeof row.byteSize === "number" ? row.byteSize : 0,
    capturedAt: typeof row.capturedAt === "string" ? row.capturedAt : "",
  };
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
  outcome: ReportOutcome;
  reviewedByUserId: string | null;
  reviewedBy: string | null;
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
