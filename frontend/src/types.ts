export interface PlayerInfo {
  token: string;
  nickname: string;
  score: number;
  connected: boolean;
  isHost: boolean;
}

export type HintMode = "none" | "checkpoints" | "purchase";

export interface RoomSummary {
  id: string;
  code: string;
  name: string;
  isPublic: boolean;
  playerCount: number;
  maxPlayers: number;
  rounds: number;
  customWordCount: number;
  customWordsOnly: boolean;
  drawingSeconds: number;
  hintMode: HintMode;
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
  state: "waiting" | "playing";
  players: PlayerInfo[];
}

export type GamePhase = "idle" | "choosing_word" | "drawing" | "round_end" | "game_end";

export interface ChatMessage {
  id: string;
  nickname: string;
  text: string;
  correct: boolean;
  system?: boolean;
  close?: boolean;
}

export interface ScoreEntry {
  token: string;
  nickname: string;
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

export type DrawTool = "pen" | ShapeType | "fill";

export interface StrokeShapePayload {
  shape: ShapeType;
  from: StrokePoint;
  to: StrokePoint;
  color: string;
  width: number;
}

// A flood fill is computed once (locally, on the drawer's own rendered
// canvas pixels) and its result - the rectangular patch of pixels it
// changed - is shipped as a base64 PNG so every other client (and late
// joiners replaying history) renders the exact same pixels, instead of each
// client re-running the fill algorithm on canvases that could have subtly
// different anti-aliasing.
export interface StrokeFillPayload {
  patchX: number;
  patchY: number;
  patchWidth: number;
  patchHeight: number;
  patchData: string;
}

export interface StrokeRecord {
  event: "draw_start" | "draw_move" | "draw_end" | "draw_shape" | "draw_fill";
  payload:
    | StrokeStartPayload
    | StrokeMovePayload
    | StrokeShapePayload
    | StrokeFillPayload
    | Record<string, never>;
}

export interface AckResponse {
  ok: boolean;
  roomId?: string;
  code?: string;
  token?: string;
  error?: string;
}
