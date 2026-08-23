import { apiBinaryRequest, apiRequest } from "./api";
import type { AuthUser } from "../store/authStore";

export interface ProfileStats {
  gamesPlayed: number;
  gamesWon: number;
  winRate: number;
  totalScore: number;
  averageScore: number;
  turnsPlayed: number;
  promptsGuessed: number;
  drawingsMade: number;
}

export interface GameParticipant {
  seatId: string;
  userId: string | null;
  displayName: string;
  nameColor: string | null;
  isAnonymous: boolean;
  finalScore: number;
  finalRank: number;
}

export interface GameSummary {
  id: string;
  roomName: string;
  scoringMode: string;
  scoringVersion: number;
  scoreLedgerVersion: number;
  ruleSnapshotVersion: number;
  promptSourceMode: "legacy_unknown" | "curated" | "custom" | "mixed" | "builtin_fallback";
  hintMode: string;
  drawingSeconds: number;
  totalRounds: number;
  playerCount: number;
  startedAt: string | null;
  finishedAt: string | null;
  participants: GameParticipant[];
}

export interface TurnGuess {
  userId: string | null;
  seatId: string | null;
  displayName: string;
  nameColor: string | null;
  isAnonymous: boolean;
  pointsAwarded: number;
  guessTimeSeconds: number;
}

export interface TurnParticipantOutcome {
  seatId: string;
  eligible: boolean;
  eligibilityReason: "eligible" | "afk" | "disconnected" | "joined_late";
  outcome: "correct" | "incorrect" | "no_attempt" | "ineligible";
  terminalState: "active" | "afk" | "disconnected" | "left" | "legacy_unknown";
  correctGuessTimeSeconds: number | null;
  wrongGuessCount: number;
  nearMissCount: number;
  hintsUsed: number;
  pointsSpentOnHints: number;
}

export interface ScoreEvent {
  id: string;
  participantSeatId: string;
  participantUserId: string | null;
  turnId: string | null;
  eventOrder: number;
  eventType: "guess_award" | "hint_charge" | "drawer_bonus" | "correction";
  pointsDelta: number;
  scoringVersion: number;
  ruleSnapshotVersion: number;
  correctsEventId: string | null;
}

export interface GameTurn {
  id: string;
  roundNumber: number;
  turnNumber: number;
  drawerUserId: string | null;
  drawerSeatId: string | null;
  drawerDisplayName: string;
  drawerNameColor: string | null;
  drawerIsAnonymous: boolean;
  prompt: string;
  durationSeconds: number;
  promptVersionId: string | null;
  promptSourceKind: "legacy_unknown" | "curated" | "custom" | "builtin_fallback";
  strokeCount: number;
  /** Absent for turns played before drawings were kept. */
  drawingStatus: "ready" | "unavailable" | "deleted" | "pending" | "failed" | null;
  promptOffers: PromptOffer[];
  guesses: TurnGuess[];
  participantOutcomes: TurnParticipantOutcome[];
}

export interface PromptOffer {
  position: number;
  prompt: string;
  selected: boolean;
  sourceKind: "curated" | "custom" | "builtin_fallback";
  promptVersionId: string | null;
  sourceRevisionIds: string[];
}

export interface GameRuleSnapshot {
  schemaVersion: number;
  scoring: {
    mode: string;
    version: number;
    default: {
      minimumGuessPoints: number;
      maximumGuessPoints: number;
      algorithm: string;
    };
    pressure: {
      maximumGuessPoints: number;
      minimumGuessPoints: number;
      decayPerReferenceSecond: number;
      referenceSeconds: number;
      postGuessMultiplier: number;
    };
    drawerBonus: string;
  };
  hints: {
    mode: string;
    minimumHiddenLetters: number;
    escalatingBaseCost: number;
    maximumSpendPerTurn: number;
    wheel: {
      vowelBaseCost: number;
      consonantBaseCost: number;
      minimumFrequencyMultiplier: number;
      maximumFrequencyMultiplier: number;
    };
  };
  drawing: {
    seconds: number;
    allowedTools: string[];
    colorMode: string;
    allowedColors: string[] | null;
  };
  prompt: {
    language: string;
    hideMaskedPrompt: boolean;
    sourceRevisionIds: string[];
  };
}

export type GameDetail = GameSummary & {
  // Empty only for legacy version-zero games.
  ruleSnapshot: GameRuleSnapshot | Record<string, never>;
  turns: GameTurn[];
  scoreEvents: ScoreEvent[];
};

export const HISTORY_PAGE_SIZE = 10;

export function fetchProfile(userId: string) {
  return apiRequest<{ user: AuthUser; stats: ProfileStats }>(
    `/api/users/${encodeURIComponent(userId)}/stats`,
  );
}

export function fetchGames(userId: string, offset: number) {
  return apiRequest<{ games: GameSummary[]; hasMore: boolean }>(
    `/api/users/${encodeURIComponent(userId)}/games`
      + `?limit=${HISTORY_PAGE_SIZE}&offset=${offset}`,
  );
}

export function fetchGameDetail(gameId: string) {
  return apiRequest<GameDetail>(`/api/games/${encodeURIComponent(gameId)}`);
}

/** The stored drawing for one turn, in the same wire format a live one uses. */
export async function fetchGameDrawing(
  gameId: string,
  turnId: string,
): Promise<ArrayBuffer> {
  return apiBinaryRequest(
    `/api/games/${encodeURIComponent(gameId)}/turns/${encodeURIComponent(turnId)}/drawing`,
  );
}

/** "12 Aug 2026, 14:05" — locale-formatted, with the raw value as a fallback. */
export function formatTimestamp(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  return minutes > 0 ? `${minutes}m ${whole % 60}s` : `${whole}s`;
}
