export interface PlayerInfo {
  playerId: string;
  nickname: string;
  nameColor?: string;
  /** Guests render in grey italics; the flag is what drives that styling. */
  isAnonymous?: boolean;
  score: number;
  connected: boolean;
  isHost: boolean;
  isSpectator: boolean;
  isAfk: boolean;
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
export type ScoringMode = "none" | "default" | "pressure";

export interface PromptListSummary {
  slug: string;
  name: string;
  description: string;
  language: string;
  promptCount: number;
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
  customPromptCount: number;
  customPromptsOnly: boolean;
  drawingSeconds: number;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  promptListSlugs?: string[];
  state: "waiting" | "playing";
}

export interface RoomStatePayload {
  id: string;
  code: string;
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  customPromptCount: number;
  customPromptsOnly: boolean;
  drawingSeconds: number;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  promptListSlugs?: string[];
  state: "waiting" | "playing";
  lastGameScores?: ScoreEntry[];
  lastGameHighlights?: GameHighlight[];
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
  customPrompts: string;
  customPromptsOnly: boolean;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  promptListSlugs?: string[];
}

export type GamePhase = "idle" | "choosing_prompt" | "drawing" | "turn_results" | "game_end";

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

export interface TurnScoreEntry extends ScoreEntry {
  delta: number;
  previousRank: number;
  newRank: number;
}

export interface TurnEndedPayload {
  prompt: string;
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
  scores: TurnScoreEntry[];
}

/**
 * How one player's turn score was arrived at: hints are bought on credit and
 * settled against the guess, so the gross figure can't be recovered from the
 * net one once the deduction clamps at zero.
 */
export interface GuessBreakdown {
  points: number;
  basePoints: number;
  hintSpend: number;
}

/**
 * One superlative from a finished game. Every kind is derived from guess counts
 * and timings alone - never from points - so the set means the same thing in a
 * no-scoring game as in a scored one. The server omits any highlight the game
 * gave it nothing to say about, so this list is often shorter than the union
 * of kinds and is sometimes empty.
 */
export type GameHighlight =
  | {
      kind: "hardest_prompt";
      prompt: string;
      correctGuessCount: number;
      totalGuesserCount: number;
    }
  | ({ kind: "fastest_guess"; prompt: string; seconds: number } & HighlightName)
  | ({ kind: "best_drawer"; guessRatio: number } & HighlightName)
  | ({ kind: "quickest_average"; seconds: number } & HighlightName);

/** The fields a highlight naming a player renders that name from. */
export interface HighlightName {
  nickname: string;
  nameColor?: string;
  isAnonymous?: boolean;
}

export interface GameEndedPayload {
  scores: ScoreEntry[];
  highlights?: GameHighlight[];
  drawings: DrawingRecapMetadata[];
}

export interface DrawingRecapMetadata {
  index: number;
  roundNumber: number;
  turnNumber: number;
  drawerId: string;
  drawerNickname: string;
  drawerNameColor?: string;
  prompt: string;
  actionCount: number;
  /** False once the room gave this bitmap up to stay inside its recap budget. */
  available?: boolean;
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

export type DrawTool = "brush" | "eraser" | ShapeType | "fill";

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
  field?: string;
  isAnonymous?: boolean;
  needsRebind?: boolean;
  /** The player slots are taken - spectating is still open. */
  roomFull?: boolean;
}

export interface RoomPreviewResponse extends AckResponse {
  room?: RoomSummary;
}
