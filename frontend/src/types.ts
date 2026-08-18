export interface PlayerInfo {
  playerId: string;
  nickname: string;
  nameColor?: string;
  score: number;
  connected: boolean;
  isHost: boolean;
  isSpectator: boolean;
  isAfk: boolean;
  isAnonymous?: boolean;
  kickVotes?: string[];
  afkVotes?: string[];
}

export interface ModerationState {
  eligibleVoterIds: string[];
  requiredVotes: number;
}

export interface RestartVoteState {
  status: "voting" | "approved";
  proposerId: string;
  proposerNickname: string;
  eligibleVoterIds: string[];
  yesVoterIds: string[];
  noVoterIds: string[];
  castVotes: Array<{ playerId: string; vote: boolean }>;
  requiredVotes: number;
  expiresAt: number;
  restartAt: number | null;
}

export type HintMode = "none" | "checkpoints" | "purchase" | "wheel";
export type ScoringMode = "none" | "default";

export interface WordListSummary {
  slug: string;
  name: string;
  description: string;
  language: string;
  wordCount: number;
  isBundled: boolean;
  version: number;
}

export interface RoomSummary {
  id: string;
  code: string;
  name: string;
  isPublic: boolean;
  playerCount: number;
  spectatorCount: number;
  maxPlayers: number;
  isFull: boolean;
  rounds: number;
  customWordCount: number;
  customWordsOnly: boolean;
  drawingSeconds: number;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeeSolution: boolean;
  hideMaskedPrompt: boolean;
  wordListSlugs?: string[];
  state: "waiting" | "playing";
}

export interface RoomStatePayload {
  id: string;
  code: string;
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  customWordCount: number;
  customWordsOnly: boolean;
  drawingSeconds: number;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeeSolution: boolean;
  hideMaskedPrompt: boolean;
  wordListSlugs?: string[];
  state: "waiting" | "playing";
  lastGameScores?: ScoreEntry[];
  lastGameDrawings?: DrawingRecapMetadata[];
  moderation: ModerationState;
  restartVote?: RestartVoteState | null;
  restartVoteCooldownUntil?: number;
  players: PlayerInfo[];
}

export interface EditableRoomSettings {
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  drawingSeconds: number;
  customWords: string;
  customWordsOnly: boolean;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeeSolution: boolean;
  hideMaskedPrompt: boolean;
  wordListSlugs?: string[];
}

export type GamePhase = "idle" | "choosing_word" | "drawing" | "round_end" | "game_end";

export interface ChatMessage {
  id: string;
  playerId?: string;
  nickname: string;
  nameColor?: string;
  isAnonymous?: boolean;
  text: string;
  correct: boolean;
  system?: boolean;
  close?: boolean;
  restricted?: boolean;
  isSpectator?: boolean;
}

export interface ScoreEntry {
  playerId: string;
  nickname: string;
  nameColor?: string;
  isAnonymous?: boolean;
  score: number;
}

export interface RoundScoreEntry extends ScoreEntry {
  delta: number;
  previousRank: number;
  newRank: number;
}

export interface RoundEndedPayload {
  word: string;
  drawerId: string;
  drawerBonus: number;
  seconds?: number;
  guesses: {
    playerId: string;
    nickname: string;
    nameColor?: string;
    isAnonymous?: boolean;
    seconds: number;
  }[];
  scores: RoundScoreEntry[];
}

export interface GameEndedPayload {
  scores: ScoreEntry[];
  drawings: DrawingRecapMetadata[];
}

export interface DrawingRecapMetadata {
  index: number;
  roundNumber: number;
  turnNumber: number;
  drawerId: string;
  drawerNickname: string;
  drawerNameColor?: string;
  word: string;
  actionCount: number;
}

export interface DrawingRecapEntry extends DrawingRecapMetadata {
  canvas: unknown;
}

export interface DrawingRecapResponse extends AckResponse {
  drawing?: DrawingRecapEntry;
}

export interface StrokePoint {
  x: number;
  y: number;
}

export interface StrokeStartPayload {
  x: number;
  y: number;
  color: string;
  width: number;
}

export interface StrokeMovePayload {
  points: StrokePoint[];
}

export type ShapeType = "rectangle" | "ellipse" | "triangle";

export type DrawTool = "pen" | "eraser" | ShapeType | "fill";

export interface StrokeShapePayload {
  shape: ShapeType;
  from: StrokePoint;
  to: StrokePoint;
  color: string;
  width: number;
}

export interface StrokeFillPayload {
  x: number;
  y: number;
  color: string;
}

export interface CanvasSyncPayload {
  v: number;
  a: unknown[];
}

export interface AckResponse {
  ok: boolean;
  roomId?: string;
  code?: string;
  playerId?: string;
  error?: string;
  sessionExpired?: boolean;
  needsRebind?: boolean;
}

export interface RoomPreviewResponse extends AckResponse {
  room?: RoomSummary;
}
