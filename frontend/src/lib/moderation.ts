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

/** Where a complaint happened, and so which incident it belongs to.

`room` groups by the room instance it was filed in; `lobby` shares one bucket
per reported account, the lobby having no instance to name; `unscoped` cited
nothing, names no place to look, and stands alone. */
export type ReportScope = "room" | "lobby" | "profile" | "unscoped";

/** One complaint inside an incident: who made it, in what words, and why.

It carries no evidence of its own - the incident merges that above these,
because several reporters describing one thing are describing one thread seen
from several seats. */
export interface IncidentReport {
  id: string;
  reporterUserId: string | null;
  reason: ReportReason;
  details: string;
  contextSnapshot: Record<string, unknown>;
  gameId: string | null;
  turnId: string | null;
  createdAt: string;
  /** The canvas as this reporter saw it, if they attached one. */
  drawing: PlayerReportDrawing | null;
  /** What became of the picture this complaint was about; null when it was
      not about one. The reported picture is never recoverable - an upload
      deletes the one it replaces - so this says what is there instead,
      never that the old one can be shown. */
  pictureStatus: PictureStatus | null;
}

/** `same` - still the picture that was complained about. `replaced` - a
different one is there now. `removed` - there is none, which is a different
thing from a different one and reads as the opposite of it if they are
conflated. */
export type PictureStatus = "same" | "replaced" | "removed";

/** What became of the picture an incident is about, said once for the case.

`removed` is the state worth separating: a picture a moderator has already
taken down would otherwise read as "a different picture now", which is the
opposite of what was done to it - and the moderator reading that is often the
one who did it, moments earlier, from this very case. */
export interface IncidentPicture {
  status: PictureStatus;
  /** Whether somebody carried the removal out, rather than the player taking
      their own picture down - which is not a punishment and sets no block. */
  removedByModerator: boolean;
  removedAt: string | null;
  /** Removed through one of this incident's own reports. */
  removedFromThisIncident: boolean;
}

/** What was last decided about this same incident, when there has been one.

A decided incident is closed for good, so a fresh complaint about the same
person in the same place is a new incident rather than a reopening. This is
what stops it arriving looking untouched. */
export interface PriorDecision {
  outcome: ReportOutcome;
  decidedAt: string | null;
  /** Resolved when read, never stored beside the case. Null if that account
      is gone. */
  decidedBy: string | null;
  /** The note that decision was required to carry. Written for other
      moderators, which is what makes it worth showing here. */
  note: string | null;
  /** How many times this same incident has been decided before. */
  priorDecisions: number;
}

/** A line of an incident's merged thread, and who complained about it. */
export interface IncidentEvidence extends PlayerReportMessageEvidence {
  /** The reports that cited this line. Empty for context the server copied
      around somebody else's citation - `role` says the same thing. */
  citedBy: string[];
}

/** One reported account, in one place: the reports about it read as one case.

This is what a moderator reads and decides. `reporterCount` is shown and
deliberately orders nothing - six reports is six people who chose to complain,
not six times the evidence, and letting a pile-on jump the queue would reward
arranging one. */
export interface ModerationIncident {
  /** The oldest report's id. Stable as more reporters arrive, and already a
      row every decision route accepts. */
  id: string;
  reportedUserId: string | null;
  /** Null when the account is gone. */
  reportedPlayer: ReportedPlayerContext | null;
  scope: ReportScope;
  reporterCount: number;
  /** The distinct reasons given, in the order they were first given. */
  reasons: ReportReason[];
  openedAt: string;
  latestReportedAt: string;
  status: ReportStatus;
  reports: IncidentReport[];
  /** Every report's evidence as one thread, each line once, as it was said. */
  evidence: IncidentEvidence[];
  /** Every canvas the reports carried - the drawing as it changed under them. */
  drawings: (PlayerReportDrawing & { reportId: string })[];
  outcome: ReportOutcome;
  reviewedByUserId: string | null;
  reviewedBy: string | null;
  resolutionNote: string | null;
  reviewedAt: string | null;
  /** Which moderator action decided it; null while it waits. */
  decisionGroupId: string | null;
  /** What became of the picture this incident is about; null when it is not
      about one. The decision is still about the picture the account carries
      now, which is the one Remove picture acts on. */
  picture: IncidentPicture | null;
  /** Null on a first complaint, which is most of them. */
  priorDecision: PriorDecision | null;
}

/** The ledger cap a resolution note has to fit inside. */
export const MAX_RESOLUTION_NOTE = 2000;

/** The note a "decide it the same way again" carries.

Whoever reads this case next gets what the moderator was looking at when they
pressed the button, rather than a bare "dismissed" that sends them hunting for
the decision it was deferring to. Composed rather than typed, because the whole
point of the shortcut is that there is nothing left to say; the earlier note is
quoted, because it is somebody else's words.

The outcome's label and the formatted time are passed in rather than derived:
how a decision is named and how a moment is written are the page's business,
and both belong to the reader's own settings. */
export function composeRepeatNote(
  prior: PriorDecision,
  outcomeLabel: string,
  when: string | null,
): string {
  const head =
    `Already ${outcomeLabel.toLowerCase()}` +
    (when ? ` on ${when}` : "") +
    (prior.decidedBy ? ` by ${prior.decidedBy}` : "") +
    (prior.priorDecisions > 1 ? `, and ${prior.priorDecisions} times in all` : "") +
    ".";
  if (!prior.note) return head;
  // The quote is what gives, so the head - which says what was decided and by
  // whom - always survives the cap intact.
  const room = MAX_RESOLUTION_NOTE - head.length - " Their note: “”".length;
  if (room <= 1) return head;
  const quoted =
    prior.note.length <= room ? prior.note : `${prior.note.slice(0, room - 1)}…`;
  return `${head} Their note: “${quoted}”`;
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

/** The queue as incidents: reports of one thing, read once.

`limit` and `offset` page incidents rather than reports, because an incident
is the unit a moderator reads and decides. */
export function listModerationReports(
  status?: ReportStatus,
  input: { limit?: number; offset?: number } = {},
): Promise<{ incidents: ModerationIncident[]; total: number; hasMore: boolean }> {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (input.limit !== undefined) query.set("limit", String(input.limit));
  if (input.offset !== undefined) query.set("offset", String(input.offset));
  const suffix = query.size > 0 ? `?${query}` : "";
  return apiRequest(`/api/moderation/reports${suffix}`);
}

/** The drawing a report carries, in the wire format a live canvas uses. */
export function fetchReportDrawing(reportId: string): Promise<ArrayBuffer> {
  return apiBinaryRequest(`/api/moderation/reports/${reportId}/drawing`);
}

/** How many closed cases one page of the queue shows. */
export const CLOSED_CASES_PAGE_SIZE = 25;

/** Decided incidents, player and content as one stream, newest decision first.

Paged by the server rather than merged here, because closed cases accumulate
for as long as the service runs and the newest are the ones worth reaching. The
page counts decisions: an incident five people reported is one entry here, as
it was one entry in the queue. */
export function listClosedCases(input: { limit?: number; offset?: number } = {}): Promise<{
  players: ModerationIncident[];
  content: ContentIncident[];
  hasMore: boolean;
}> {
  const limit = input.limit ?? CLOSED_CASES_PAGE_SIZE;
  const offset = input.offset ?? 0;
  return apiRequest(`/api/moderation/closed-cases?limit=${limit}&offset=${offset}`);
}

/** Decide an incident. The id names one of its reports; every report of the
    incident is decided with it, under one note and one step-up. */
export function reviewModerationReport(
  reportId: string,
  status: Exclude<ReportStatus, "pending">,
  note: string,
): Promise<ModerationIncident> {
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
  /** The reported messages behind it - the player's own words, from every
      report the decision covered. */
  messages: { text: string; at: string | null }[];
  /** The canvases those reports carried, if any did - the player's own work. */
  drawings: (PlayerReportDrawing & { reportId: string })[];
}

/** One drawing behind the caller's own warning. */
export function fetchWarningDrawing(
  warningId: string,
  reportId: string,
): Promise<ArrayBuffer> {
  return apiBinaryRequest(`/api/warnings/${warningId}/drawings/${reportId}`);
}

/** One drawing behind the caller's own suspension, reachable while suspended. */
export function fetchSuspensionDrawing(reportId: string): Promise<ArrayBuffer> {
  return apiBinaryRequest(`/api/suspension/drawings/${reportId}`);
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

/** One complaint about a piece of prompt content. The target it is about is
    stated once on the incident above it, being shared by construction. */
export interface ContentIncidentReport {
  id: string;
  reporterUserId: string | null;
  reason: string;
  details: string;
  createdAt: string;
}

/** One reported list or prompt version, and every complaint about it.

The target already names the incident, so unlike a player report there is no
place or moment to bound it with - and no scope to record. */
export interface ContentIncident {
  /** The oldest report's id, which the review route accepts. */
  id: string;
  reportedOwnerUserId: string | null;
  promptListId: string | null;
  promptVersionId: string | null;
  targetType: "list" | "prompt";
  listName: string | null;
  prompt: string | null;
  reporterCount: number;
  reasons: string[];
  openedAt: string;
  latestReportedAt: string;
  status: ReportStatus;
  reports: ContentIncidentReport[];
  outcome: ReportOutcome;
  reviewedByUserId: string | null;
  reviewedBy: string | null;
  resolutionNote: string | null;
  moderationState: "active" | "hidden" | null;
  reviewedAt: string | null;
  decisionGroupId: string | null;
}

export function listPromptContentReports(
  status?: ReportStatus,
  input: { limit?: number; offset?: number } = {},
): Promise<{ incidents: ContentIncident[]; total: number; hasMore: boolean }> {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (input.limit !== undefined) query.set("limit", String(input.limit));
  if (input.offset !== undefined) query.set("offset", String(input.offset));
  const suffix = query.size > 0 ? `?${query}` : "";
  return apiRequest(`/api/moderation/prompt-content-reports${suffix}`);
}

/** Resolve or dismiss a content report.

`moderationState` is what actually hides the reported list or prompt; a report
resolved without it is a decision recorded and nothing acted on. */
export function reviewPromptContentReport(
  reportId: string,
  status: Exclude<ReportStatus, "pending">,
  note: string,
  moderationState?: "active" | "hidden",
): Promise<ContentIncident> {
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
