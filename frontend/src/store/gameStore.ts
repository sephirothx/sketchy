import { create } from "zustand";
import type {
  ChatMessage,
  DrawingRecapMetadata,
  GameEndedPayload,
  GamePhase,
  HintMode,
  ModerationState,
  PlayerInfo,
  RoomStatePayload,
  RestartVoteState,
  GuessBreakdown,
  RoundEndedPayload,
  ScoringMode,
} from "../types";

interface GameStore {
  playerId: string | null;
  /**
   * Set while deliberately leaving a room (leave, kick, or a seat taken over
   * elsewhere). Clearing the session makes the room route briefly look like an
   * un-joined visitor, which would otherwise flash the invite screen and fire
   * a pointless rejoin probe on the way out.
   */
  isExitingRoom: boolean;
  roomId: string | null;
  code: string | null;
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
  wordListSlugs: string[];
  roomState: "waiting" | "playing";
  players: PlayerInfo[];
  moderation: ModerationState;
  restartVote: RestartVoteState | null;
  restartVoteCooldownUntil: number;

  phase: GamePhase;
  drawerId: string | null;
  maskedWord: string;
  myWord: string | null;
  guessedWord: string | null;
  wordChoices: string[];
  roundNumber: number;
  totalRounds: number;
  phaseSeconds: number;
  phaseStartedAt: number;
  nextHintCost: number | null;
  letterPrices: Record<string, number> | null;
  /** Points committed to hints so far this turn, and the ceiling on them. */
  hintSpend: number;
  hintBudget: number;
  /** Set when I guess correctly; cleared when the next turn starts. */
  lastGuessBreakdown: GuessBreakdown | null;

  messages: ChatMessage[];
  lastRoundResult: RoundEndedPayload | null;
  finalScores: GameEndedPayload["scores"] | null;
  drawingRecap: DrawingRecapMetadata[];
  error: string | null;

  setSession: (session: {
    roomId: string;
    code: string;
    playerId: string;
  }) => void;
  clearSession: () => void;
  setExitingRoom: (isExiting: boolean) => void;
  setRoomState: (payload: RoomStatePayload) => void;
  addMessage: (message: ChatMessage) => void;
  applyGuessPoints: (playerId: string, points: number) => void;
  startChoosing: (payload: {
    drawerId: string;
    roundNumber: number;
    totalRounds: number;
    seconds: number;
  }) => void;
  setMyWordChoices: (choices: string[], seconds: number) => void;
  startDrawing: (payload: {
    drawerId: string;
    maskedWord: string;
    roundNumber: number;
    totalRounds: number;
    seconds: number;
    hintCost?: number | null;
    letterPrices?: Record<string, number> | null;
    hintSpend?: number;
    hintBudget?: number;
  }) => void;
  setMyWord: (word: string | null) => void;
  setGuessedWord: (word: string | null, breakdown?: GuessBreakdown | null) => void;
  setMaskedWord: (word: string) => void;
  setHintRevealed: (payload: {
    maskedWord: string;
    hintCost?: number | null;
    letterPrices?: Record<string, number> | null;
    hintSpend?: number;
  }) => void;
  endRound: (payload: RoundEndedPayload) => void;
  endGame: (payload: GameEndedPayload) => void;
  dismissGameEnd: () => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const initialGameFields = {
  phase: "idle" as GamePhase,
  drawerId: null as string | null,
  maskedWord: "",
  myWord: null as string | null,
  guessedWord: null as string | null,
  wordChoices: [] as string[],
  roundNumber: 0,
  totalRounds: 0,
  phaseSeconds: 0,
  phaseStartedAt: 0,
  nextHintCost: null as number | null,
  letterPrices: null as Record<string, number> | null,
  hintSpend: 0,
  hintBudget: 300,
  lastGuessBreakdown: null as GuessBreakdown | null,
  messages: [] as ChatMessage[],
  lastRoundResult: null as RoundEndedPayload | null,
  finalScores: null as GameEndedPayload["scores"] | null,
  drawingRecap: [] as DrawingRecapMetadata[],
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
  customWordCount: 0,
  customWordsOnly: false,
  drawingSeconds: 90,
  hintMode: "checkpoints" as HintMode,
  scoringMode: "default" as ScoringMode,
  spectatorsSeeSolution: false,
  hideMaskedPrompt: false,
  wordListSlugs: ["english_standard"],
  roomState: "waiting",
  players: [],
  moderation: { eligibleVoterIds: [], requiredVotes: 1 },
  restartVote: null,
  restartVoteCooldownUntil: 0,
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
      customWordCount: payload.customWordCount,
      customWordsOnly: payload.customWordsOnly,
      drawingSeconds: payload.drawingSeconds,
      hintMode: payload.hintMode,
      scoringMode: payload.scoringMode ?? "default",
      spectatorsSeeSolution: payload.spectatorsSeeSolution ?? false,
      hideMaskedPrompt: payload.hideMaskedPrompt ?? false,
      wordListSlugs: payload.wordListSlugs?.length ? payload.wordListSlugs : ["english_standard"],
      roomState: payload.state,
      finalScores: payload.lastGameScores?.length
        ? payload.lastGameScores
        : payload.state === "playing" ? null : state.finalScores,
      drawingRecap: payload.lastGameDrawings ?? state.drawingRecap,
      moderation: payload.moderation,
      restartVote: payload.restartVote ?? null,
      restartVoteCooldownUntil: payload.restartVoteCooldownUntil ?? 0,
      players: payload.players,
    })),
  addMessage: (message) => set((s) => ({ messages: [...s.messages.slice(-99), message] })),
  applyGuessPoints: (playerId, points) =>
    set((s) => ({
      players: s.players.map((p) => (p.playerId === playerId ? { ...p, score: p.score + points } : p)),
    })),
  startChoosing: ({ drawerId, roundNumber, totalRounds, seconds }) =>
    set({
      phase: "choosing_word",
      drawerId,
      roundNumber,
      totalRounds,
      phaseSeconds: seconds,
      phaseStartedAt: Date.now(),
      maskedWord: "",
      myWord: null,
      guessedWord: null,
      wordChoices: [],
      lastRoundResult: null,
    }),
  setMyWordChoices: (choices, seconds) =>
    set({ wordChoices: choices, phaseSeconds: seconds, phaseStartedAt: Date.now() }),
  startDrawing: ({ drawerId, maskedWord, roundNumber, totalRounds, seconds, hintCost, letterPrices, hintSpend, hintBudget }) =>
    set((s) => ({
      phase: "drawing",
      drawerId,
      maskedWord,
      roundNumber,
      totalRounds,
      phaseSeconds: seconds,
      phaseStartedAt: Date.now(),
      wordChoices: [],
      nextHintCost: hintCost ?? null,
      letterPrices: letterPrices ?? null,
      // Driven by both turn_started and sync_game, so a mid-turn reconnect
      // restores the real spend instead of zeroing it.
      hintSpend: hintSpend ?? 0,
      hintBudget: hintBudget ?? s.hintBudget,
      lastGuessBreakdown: null,
    })),
  setMyWord: (word) => set({ myWord: word }),
  setGuessedWord: (word, breakdown) =>
    set((s) => ({
      guessedWord: word,
      lastGuessBreakdown: breakdown !== undefined ? breakdown : s.lastGuessBreakdown,
    })),
  setMaskedWord: (word) => set({ maskedWord: word }),
  setHintRevealed: ({ maskedWord, hintCost, letterPrices, hintSpend }) =>
    set((s) => ({
      maskedWord,
      nextHintCost: hintCost ?? s.nextHintCost,
      letterPrices: letterPrices !== undefined ? letterPrices : s.letterPrices,
      hintSpend: hintSpend ?? s.hintSpend,
    })),
  endRound: (payload) =>
    set((s) => ({
      phase: "round_end",
      lastRoundResult: payload,
      phaseSeconds: payload.seconds ?? 0,
      phaseStartedAt: Date.now(),
      players: s.players.map((p) => {
        const updated = payload.scores.find((sc) => sc.playerId === p.playerId);
        return updated ? { ...p, score: updated.score } : p;
      }),
    })),
  endGame: (payload) => set({
    phase: "game_end",
    finalScores: payload.scores,
    drawingRecap: payload.drawings ?? [],
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
    ...initialGameFields,
  }),
}));
