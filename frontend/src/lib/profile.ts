import { apiRequest } from "./api";
import type { AuthUser } from "../store/authStore";

export interface ProfileStats {
  gamesPlayed: number;
  gamesWon: number;
  winRate: number;
  totalScore: number;
  averageScore: number;
  turnsPlayed: number;
  wordsGuessed: number;
  drawingsMade: number;
}

export interface GameParticipant {
  userId: string;
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
  hintMode: string;
  drawingSeconds: number;
  totalRounds: number;
  playerCount: number;
  startedAt: string | null;
  finishedAt: string | null;
  participants: GameParticipant[];
}

export interface RoundGuess {
  userId: string;
  displayName: string;
  pointsAwarded: number;
  guessTimeSeconds: number;
}

export interface GameTurn {
  roundNumber: number;
  turnNumber: number;
  drawerUserId: string;
  drawerDisplayName: string;
  word: string;
  durationSeconds: number;
  guesses: RoundGuess[];
}

export type GameDetail = GameSummary & { turns: GameTurn[] };

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
