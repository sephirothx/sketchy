export interface PlayerInfo {
  token: string;
  nickname: string;
  nameColor?: string;
  score: number;
  connected: boolean;
  isHost: boolean;
  isSpectator: boolean;
  isAfk: boolean;
  kickVotes?: string[];
  afkVotes?: string[];
}

export type HintMode = "none" | "checkpoints" | "purchase" | "wheel";
export type ScoringMode = "none" | "default";

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
  state: "waiting" | "playing";
  lastGameScores?: ScoreEntry[];
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
}

export type GamePhase = "idle" | "choosing_word" | "drawing" | "round_end" | "game_end";

export interface ChatMessage {
  id: string;
  token?: string;
  nickname: string;
  nameColor?: string;
  text: string;
  correct: boolean;
  system?: boolean;
  close?: boolean;
  restricted?: boolean;
  isSpectator?: boolean;
}

export interface ScoreEntry {
  token: string;
  nickname: string;
  nameColor?: string;
  score: number;
}

export interface RoundScoreEntry extends ScoreEntry {
  delta: number;
  previousRank: number;
  newRank: number;
}

export interface RoundEndedPayload {
  word: string;
  drawerToken: string;
  drawerBonus: number;
  seconds?: number;
  guesses: {
    token: string;
    nickname: string;
    nameColor?: string;
    seconds: number;
  }[];
  scores: RoundScoreEntry[];
}

export interface GameEndedPayload {
  scores: ScoreEntry[];
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
  token?: string;
  error?: string;
  invalidToken?: boolean;
}

export interface RoomPreviewResponse extends AckResponse {
  room?: RoomSummary;
}
