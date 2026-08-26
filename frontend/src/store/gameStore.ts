import { create } from "zustand";
import { DEFAULT_ALLOWED_TOOLS, DEFAULT_COLOR_MODE } from "../lib/drawingRules";
import type {
  ChatMessage,
  ColorblindSafeSuggestion,
  ColorMode,
  DrawingToolGroup,
  DrawingRecapMetadata,
  GameEndedPayload,
  GameHighlight,
  GamePhase,
  HintMode,
  ModerationState,
  PlayerInfo,
  PromptLanguage,
  RoomStatePayload,
  RestartVoteState,
  GuessBreakdown,
  TurnEndedPayload,
  ScoringMode,
} from "../types";

interface GameStore {
  playerId: string | null;
  /**
   * Set while deliberately leaving a room (leave, kick, or a seat taken over
   * elsewhere). Clearing the session makes the room route briefly look like an
   * un-joined visitor, which would otherwise flash the invite screen and fire
   * a pointless reconnect probe on the way out.
   */
  isExitingRoom: boolean;
  roomId: string | null;
  code: string | null;
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
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
  promptLanguage: PromptLanguage;
  promptListSlugs: string[];
  roomState: "waiting" | "playing";
  players: PlayerInfo[];
  moderation: ModerationState;
  restartVote: RestartVoteState | null;
  restartVoteCooldownUntil: number;
  colorblindSafeSuggestion: ColorblindSafeSuggestion | null;

  phase: GamePhase;
  drawerId: string | null;
  maskedPrompt: string;
  myPrompt: string | null;
  guessedPrompt: string | null;
  promptChoices: string[];
  roundNumber: number;
  totalRounds: number;
  phaseSeconds: number;
  phaseStartedAt: number;
  /** The phase's full length. phaseSeconds is rebased to the remaining time
      by sync_game, so ring/bar fractions divide by this instead. */
  phaseDurationSeconds: number;
  /** Per-player elapsed seconds for correct guesses this turn, derived
      client-side from correct_guess events (lost on mid-turn reconnect). */
  turnCorrectGuesses: Record<string, number>;
  nextHintCost: number | null;
  letterPrices: Record<string, number> | null;
  /** Points committed to hints so far this turn, and the ceiling on them. */
  hintSpend: number;
  maxHintSpend: number;
  /** Set when I guess correctly; cleared when the next turn starts. */
  lastGuessBreakdown: GuessBreakdown | null;

  messages: ChatMessage[];
  lastTurnResult: TurnEndedPayload | null;
  finalScores: GameEndedPayload["scores"] | null;
  drawingRecap: DrawingRecapMetadata[];
  gameHighlights: GameHighlight[];
  error: string | null;

  setSession: (session: {
    roomId: string;
    code: string;
    playerId: string;
  }) => void;
  clearSession: () => void;
  setExitingRoom: (isExiting: boolean) => void;
  setRoomState: (payload: RoomStatePayload) => void;
  setColorblindSafeSuggestion: (suggestion: ColorblindSafeSuggestion) => void;
  addMessage: (message: ChatMessage) => void;
  applyGuessPoints: (playerId: string, points: number) => void;
  recordCorrectGuess: (playerId: string) => void;
  startChoosing: (payload: {
    isSync?: boolean;
    drawerId: string;
    roundNumber: number;
    totalRounds: number;
    seconds: number;
  }) => void;
  setMyPromptChoices: (choices: string[], seconds: number) => void;
  startDrawing: (payload: {
    isSync?: boolean;
    drawerId: string;
    maskedPrompt: string;
    roundNumber: number;
    totalRounds: number;
    seconds: number;
    hintCost?: number | null;
    letterPrices?: Record<string, number> | null;
    hintSpend?: number;
    maxHintSpend?: number;
  }) => void;
  setMyPrompt: (prompt: string | null) => void;
  setGuessedPrompt: (prompt: string | null, breakdown?: GuessBreakdown | null) => void;
  setMaskedPrompt: (prompt: string) => void;
  setHintRevealed: (payload: {
    maskedPrompt: string;
    hintCost?: number | null;
    letterPrices?: Record<string, number> | null;
    hintSpend?: number;
  }) => void;
  endTurn: (payload: TurnEndedPayload) => void;
  endGame: (payload: GameEndedPayload) => void;
  dismissGameEnd: () => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const initialGameFields = {
  phase: "idle" as GamePhase,
  drawerId: null as string | null,
  maskedPrompt: "",
  myPrompt: null as string | null,
  guessedPrompt: null as string | null,
  promptChoices: [] as string[],
  roundNumber: 0,
  totalRounds: 0,
  phaseSeconds: 0,
  phaseStartedAt: 0,
  phaseDurationSeconds: 0,
  turnCorrectGuesses: {},
  nextHintCost: null as number | null,
  letterPrices: null as Record<string, number> | null,
  hintSpend: 0,
  maxHintSpend: 300,
  lastGuessBreakdown: null as GuessBreakdown | null,
  messages: [] as ChatMessage[],
  lastTurnResult: null as TurnEndedPayload | null,
  finalScores: null as GameEndedPayload["scores"] | null,
  drawingRecap: [] as DrawingRecapMetadata[],
  gameHighlights: [] as GameHighlight[],
};

export const useGameStore = create<GameStore>((set) => ({
  playerId: null,
  isExitingRoom: false,
  roomId: null,
  code: null,
  name: "",
  isPublic: true,
  maxPlayers: 8,
  rounds: 3,
  customPromptCount: 0,
  customPromptsOnly: false,
  drawingSeconds: 90,
  hintMode: "checkpoints" as HintMode,
  scoringMode: "default" as ScoringMode,
  spectatorsSeePrompt: false,
  hideMaskedPrompt: false,
  allowedTools: DEFAULT_ALLOWED_TOOLS,
  colorMode: DEFAULT_COLOR_MODE,
  promptLanguage: "en",
  promptListSlugs: ["english_standard"],
  roomState: "waiting",
  players: [],
  moderation: { eligibleVoterIds: [], requiredVotes: 1 },
  restartVote: null,
  restartVoteCooldownUntil: 0,
  colorblindSafeSuggestion: null,
  error: null,
  ...initialGameFields,

  setSession: ({ roomId, code, playerId }) => {
    // Nothing is persisted: the session cookie is the credential and the room
    // code comes from the URL.
    set({ roomId, code, playerId });
  },
  clearSession: () => {
    set({ playerId: null, roomId: null, code: null });
  },
  setExitingRoom: (isExitingRoom) => set({ isExitingRoom }),
  setRoomState: (payload) =>
    set((state) => ({
      roomId: payload.id,
      code: payload.code,
      name: payload.name,
      isPublic: payload.isPublic,
      maxPlayers: payload.maxPlayers,
      rounds: payload.rounds,
      customPromptCount: payload.customPromptCount,
      customPromptsOnly: payload.customPromptsOnly,
      drawingSeconds: payload.drawingSeconds,
      hintMode: payload.hintMode,
      scoringMode: payload.scoringMode ?? "default",
      spectatorsSeePrompt: payload.spectatorsSeePrompt ?? false,
      hideMaskedPrompt: payload.hideMaskedPrompt ?? false,
      allowedTools: payload.allowedTools ?? DEFAULT_ALLOWED_TOOLS,
      colorMode: payload.colorMode ?? DEFAULT_COLOR_MODE,
      promptLanguage: payload.promptLanguage ?? "en",
      promptListSlugs: payload.promptListSlugs?.length ? payload.promptListSlugs : ["english_standard"],
      roomState: payload.state,
      finalScores: payload.lastGameScores?.length
        ? payload.lastGameScores
        : payload.state === "playing" ? null : state.finalScores,
      drawingRecap: payload.lastGameDrawings ?? state.drawingRecap,
      gameHighlights: payload.lastGameHighlights ?? state.gameHighlights,
      moderation: payload.moderation,
      restartVote: payload.restartVote ?? null,
      restartVoteCooldownUntil: payload.restartVoteCooldownUntil ?? 0,
      players: payload.players,
    })),
  setColorblindSafeSuggestion: (suggestion) =>
    set({ colorblindSafeSuggestion: suggestion.active ? suggestion : null }),
  addMessage: (message) => set((s) => ({ messages: [...s.messages.slice(-99), message] })),
  applyGuessPoints: (playerId, points) =>
    set((s) => ({
      players: s.players.map((p) => (p.playerId === playerId ? { ...p, score: p.score + points } : p)),
    })),
  recordCorrectGuess: (playerId) =>
    set((s) => ({
      turnCorrectGuesses: {
        ...s.turnCorrectGuesses,
        // phaseStartedAt is rebased by sync_game, so seconds since it only
        // cover the time since the last sync; the difference between the
        // phase's full length and what remained at that sync is the part
        // that had already elapsed.
        [playerId]: Math.max(
          0,
          Math.round(
            (Date.now() - s.phaseStartedAt) / 1000 +
              Math.max(0, s.phaseDurationSeconds - s.phaseSeconds),
          ),
        ),
      },
    })),
  startChoosing: ({ drawerId, roundNumber, totalRounds, seconds, isSync }) =>
    set((s) => ({
      phase: "choosing_prompt",
      drawerId,
      roundNumber,
      totalRounds,
      phaseSeconds: seconds,
      phaseStartedAt: Date.now(),
      // A sync mid-phase reports what is left, not how long the phase is.
      phaseDurationSeconds:
        isSync && s.phase === "choosing_prompt" && s.phaseDurationSeconds > 0
          ? s.phaseDurationSeconds
          : seconds,
      maskedPrompt: "",
      myPrompt: null,
      guessedPrompt: null,
      promptChoices: [],
      lastTurnResult: null,
      turnCorrectGuesses: {},
    })),
  setMyPromptChoices: (choices, seconds) =>
    set({
      promptChoices: choices,
      phaseSeconds: seconds,
      phaseStartedAt: Date.now(),
      phaseDurationSeconds: seconds,
    }),
  startDrawing: ({ drawerId, maskedPrompt, roundNumber, totalRounds, seconds, hintCost, letterPrices, hintSpend, maxHintSpend, isSync }) =>
    set((s) => ({
      phase: "drawing",
      drawerId,
      maskedPrompt,
      roundNumber,
      totalRounds,
      phaseSeconds: seconds,
      phaseStartedAt: Date.now(),
      // On a mid-turn sync the room's drawing time is the real duration; a
      // fresh page load has no better answer than that either.
      phaseDurationSeconds: isSync
        ? (s.phase === "drawing" && s.phaseDurationSeconds > 0
          ? s.phaseDurationSeconds
          : Math.max(s.drawingSeconds, seconds))
        : seconds,
      promptChoices: [],
      nextHintCost: hintCost ?? null,
      letterPrices: letterPrices ?? null,
      // Driven by both turn_started and sync_game, so a mid-turn reconnect
      // restores the real spend instead of zeroing it.
      hintSpend: hintSpend ?? 0,
      maxHintSpend: maxHintSpend ?? s.maxHintSpend,
      lastGuessBreakdown: null,
      turnCorrectGuesses: {},
    })),
  setMyPrompt: (prompt) => set({ myPrompt: prompt }),
  setGuessedPrompt: (prompt, breakdown) =>
    set((s) => ({
      guessedPrompt: prompt,
      lastGuessBreakdown: breakdown !== undefined ? breakdown : s.lastGuessBreakdown,
    })),
  setMaskedPrompt: (prompt) => set({ maskedPrompt: prompt }),
  setHintRevealed: ({ maskedPrompt, hintCost, letterPrices, hintSpend }) =>
    set((s) => ({
      maskedPrompt,
      nextHintCost: hintCost ?? s.nextHintCost,
      letterPrices: letterPrices !== undefined ? letterPrices : s.letterPrices,
      hintSpend: hintSpend ?? s.hintSpend,
    })),
  endTurn: (payload) =>
    set((s) => ({
      phase: "turn_results",
      lastTurnResult: payload,
      phaseSeconds: payload.seconds ?? 0,
      phaseStartedAt: Date.now(),
      phaseDurationSeconds: payload.seconds ?? 0,
      players: s.players.map((p) => {
        const updated = payload.scores.find((sc) => sc.playerId === p.playerId);
        return updated ? { ...p, score: updated.score } : p;
      }),
    })),
  endGame: (payload) => set({
    phase: "game_end",
    finalScores: payload.scores,
    drawingRecap: payload.drawings ?? [],
    gameHighlights: payload.highlights ?? [],
    roomState: "waiting",
  }),
  dismissGameEnd: () => set({ phase: "idle" }),
  setError: (error) => set({ error }),
  reset: () => set({
    playerId: null,
    roomId: null,
    code: null,
    players: [],
    moderation: { eligibleVoterIds: [], requiredVotes: 1 },
    restartVote: null,
    restartVoteCooldownUntil: 0,
    colorblindSafeSuggestion: null,
    ...initialGameFields,
  }),
}));

/** The local player's own row, or undefined before the roster arrives. */
export function selectMe(state: GameStore): PlayerInfo | undefined {
  return state.players.find((player) => player.playerId === state.playerId);
}

/** Whether the local player currently holds the brush - including while choosing. */
export function selectAmDrawer(state: GameStore): boolean {
  return (
    (state.phase === "drawing" || state.phase === "choosing_prompt")
    && state.drawerId === state.playerId
  );
}
