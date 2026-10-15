/**
 * Solo (#1434): one player guessing drawings from public games they were not
 * in, over REST.
 *
 * Play is local. The server chooses each drawing and hands it over under a
 * serve id of its own - never the turn's, which would lead to its drawer -
 * with the forms its prompt is judged by, encoded so a glance at the
 * network panel does not spoil it. The client replays it, runs the clock,
 * judges each guess, and reports what the drawing came to; the server
 * derives the points.
 */
import { apiBinaryRequest, apiRequest } from "./api.ts";

/** One language's prompt and the other spellings it accepts. */
export interface SoloPromptForm {
  prompt: string;
  aliases: string[];
}

/**
 * What a drawing is judged by, decoded: the player's own language and the
 * prompt in it, the other play languages' forms, and the spellings the
 * false-friend guard takes out (#1367). The shape `guessJudge` reads.
 */
export interface SoloForms {
  language: string;
  own: SoloPromptForm;
  others: Record<string, SoloPromptForm>;
  taken: string[];
}

export type SoloOutcome = "solved" | "given_up" | "timed_out";

/** A drawing served in a run. `forms` is null once it is settled, when
    `prompt` says what it was. */
export interface SoloServe {
  serveId: string;
  position: number;
  forms: string | null;
  outcome: SoloOutcome | null;
  points: number | null;
  prompt: string | null;
  promptLanguage: string | null;
}

export interface SoloRun {
  runId: string;
  mode: "free" | "daily";
  /** 5 or 10 drawings, or null: unlimited, until the first miss. */
  length: number | null;
  state: "active" | "ended" | "abandoned";
  endReason: "completed" | "missed" | "abandoned" | null;
  position: number;
  solved: number;
  points: number;
  /** The player's local date a Daily is for. */
  dailyDate: string | null;
  serves: SoloServe[];
}

/** Undo `encode_answers` (backend/app/solo_rules.py): base64, then XOR with
    the serve id's sixteen bytes. */
export function decodeSoloForms(serveId: string, encoded: string): SoloForms {
  const key = uuidBytes(serveId);
  const mixed = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0));
  const plain = mixed.map((byte, index) => byte ^ key[index % key.length]);
  return JSON.parse(new TextDecoder().decode(plain)) as SoloForms;
}

function uuidBytes(id: string): Uint8Array {
  const hex = id.replace(/-/g, "");
  const bytes = new Uint8Array(16);
  for (let index = 0; index < 16; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

/** Start a free run, abandoning the one in play. */
export function startFreeRun(length: 5 | 10 | null): Promise<SoloRun> {
  return apiRequest("/api/solo/runs", { method: "POST", body: { length } });
}

/** The free run there is to continue, if any. */
export async function fetchActiveFreeRun(): Promise<SoloRun | null> {
  const answer = await apiRequest<{ run: SoloRun | null }>("/api/solo/runs/active");
  return answer.run;
}

/** The next drawings of a run: one, or two to hold the next one ready. */
export async function serveNext(runId: string, count: 1 | 2 = 1): Promise<SoloServe[]> {
  const answer = await apiRequest<{ serves: SoloServe[] }>(
    `/api/solo/runs/${encodeURIComponent(runId)}/serves?count=${count}`,
    { method: "POST" },
  );
  return answer.serves;
}

/** A run as the server holds it: what a page reconciles with after a lost
    answer. */
export function fetchSoloRun(runId: string): Promise<SoloRun> {
  return apiRequest(`/api/solo/runs/${encodeURIComponent(runId)}`);
}

/** Report what a drawing came to, by the client's own clock. */
export function settleServe(
  serveId: string,
  outcome: SoloOutcome,
  seconds: number,
): Promise<{ serve: SoloServe; run: SoloRun }> {
  return apiRequest(`/api/solo/serves/${encodeURIComponent(serveId)}/result`, {
    method: "POST",
    body: { outcome, seconds },
  });
}

/** A served drawing's bytes through Solo's own door. Every refusal is a 404. */
export function fetchSoloDrawing(serveId: string): Promise<ArrayBuffer> {
  return apiBinaryRequest(`/api/solo/serves/${encodeURIComponent(serveId)}/drawing`);
}

/** One drawing of a Daily as played: its outcome, the seconds, and whether
    it was played after the date had ended everywhere. */
export interface SoloDailyMark {
  outcome: SoloOutcome;
  seconds: number;
  late: boolean;
}

/** A player's Daily for one date: kept as it is played, so half a Daily
    keeps its progress. */
export interface SoloDailyResult {
  date: string;
  positionsPlayed: number;
  solved: number;
  points: number;
  completed: boolean;
  marks: SoloDailyMark[];
}

export type SoloTodayState = "not_started" | "in_progress" | "done" | "unavailable";

/** What Solo's page opens on. `bests` is keyed `"5"`, `"10"`, `"unlimited"`:
    points for the first two, drawings named for the third. */
export interface SoloSummary {
  today: { date: string; state: SoloTodayState; result: SoloDailyResult | null };
  activeRunId: string | null;
  bests: Partial<Record<"5" | "10" | "unlimited", number>>;
  history: SoloDailyResult[];
  streak: number;
}

/** The player's local date, as the server takes it: `YYYY-MM-DD`. */
export function localDateKey(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** Today's Daily: created with its five drawings the first time, resumed after. */
export function openDaily(date: string): Promise<SoloRun> {
  return apiRequest(`/api/solo/daily/${encodeURIComponent(date)}`, { method: "POST" });
}

export function fetchSoloSummary(today: string): Promise<SoloSummary> {
  return apiRequest(`/api/solo/me?today=${encodeURIComponent(today)}`);
}

/** A reaction from Solo: the counts and the player's own pick, naming nobody. */
export interface SoloReaction {
  myReaction: string | null;
  reactionCounts: Record<string, number>;
}

/** React to a drawing Solo served the player, once it is settled. */
export function reactToServe(serveId: string, emoji: string | null): Promise<SoloReaction> {
  const path = `/api/solo/serves/${encodeURIComponent(serveId)}/reaction`;
  return emoji === null
    ? apiRequest(path, { method: "DELETE" })
    : apiRequest(path, { method: "PUT", body: { emoji } });
}

/** A share from Solo: whether the drawing is in the Gallery, whether the
    player shares it, until when their share waits for an open Daily, and
    whether its drawer took it out of the Gallery. */
export interface SoloShare {
  inGallery: boolean;
  sharedByMe: boolean;
  heldUntil: string | null;
  shareWithdrawn: boolean;
}

/** Share a drawing Solo served the player to the Gallery, under its drawer's
    name, or take the player's share back. */
export function shareServe(serveId: string, shared: boolean): Promise<SoloShare> {
  return apiRequest(`/api/solo/serves/${encodeURIComponent(serveId)}/share`, {
    method: shared ? "PUT" : "DELETE",
  });
}

/** Report a drawing Solo served the player. Answered as accepted even when
    they already reported its drawer: a refusal would say who drew it. */
export function reportServe(
  serveId: string,
  details: string | null,
): Promise<{ id: string | null; status: string; createdAt: string }> {
  return apiRequest(`/api/solo/serves/${encodeURIComponent(serveId)}/report`, {
    method: "POST",
    body: details ? { details } : {},
  });
}

/** The drawer's way out for every public drawing at once. */
export async function setSoloOptOut(optOut: boolean): Promise<boolean> {
  const settings = await apiRequest<{ soloOptOut: boolean }>("/api/users/me/settings", {
    method: "PATCH",
    body: { soloOptOut: optOut },
  });
  return settings.soloOptOut;
}

/** The drawer's way out for one drawing: take it out of Solo, or put it back. */
export async function setSoloWithdrawn(
  gameId: string,
  turnId: string,
  withdrawn: boolean,
): Promise<boolean> {
  const answer = await apiRequest<{ soloWithdrawn: boolean }>(
    `/api/games/${encodeURIComponent(gameId)}/turns/${encodeURIComponent(turnId)}/solo`,
    { method: withdrawn ? "DELETE" : "PUT" },
  );
  return answer.soloWithdrawn;
}
