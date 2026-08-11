import { create } from "zustand";
import type {
  ChatMessage,
  DrawingRecapMetadata,
  GameEndedPayload,
  GamePhase,
  HintMode,
  PlayerInfo,
  RoomStatePayload,
  RoundEndedPayload,
  ScoringMode,
} from "../types";
import {
  clearReconnectSecret,
  readReconnectSecret,
  writeReconnectSecret,
} from "../lib/sessionCredentials";

interface GameStore {
  nickname: string;
  playerId: string | null;
  reconnectSecret: string | null;
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
  roomState: "waiting" | "playing";
  players: PlayerInfo[];

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

  messages: ChatMessage[];
  lastRoundResult: RoundEndedPayload | null;
  finalScores: GameEndedPayload["scores"] | null;
  drawingRecap: DrawingRecapMetadata[];
  error: string | null;

  setNickname: (nickname: string) => void;
  setSession: (session: {
    roomId: string;
    code: string;
    playerId: string;
    reconnectSecret: string;
  }) => void;
  getStoredReconnectSecret: (code: string) => string | null;
  clearStoredReconnectSecret: (code: string) => void;
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
  }) => void;
  setMyWord: (word: string | null) => void;
  setGuessedWord: (word: string | null) => void;
  setMaskedWord: (word: string) => void;
  setHintRevealed: (payload: {
    maskedWord: string;
    hintCost?: number | null;
    letterPrices?: Record<string, number> | null;
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
  messages: [] as ChatMessage[],
  lastRoundResult: null as RoundEndedPayload | null,
  finalScores: null as GameEndedPayload["scores"] | null,
  drawingRecap: [] as DrawingRecapMetadata[],
};

export const useGameStore = create<GameStore>((set) => ({
  nickname: localStorage.getItem("sketchy_nickname") || "",
  playerId: null,
  reconnectSecret: null,
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
  roomState: "waiting",
  players: [],
  error: null,
  ...initialGameFields,

  setNickname: (nickname) => {
    localStorage.setItem("sketchy_nickname", nickname);
    set({ nickname });
  },
  setSession: ({ roomId, code, playerId, reconnectSecret }) => {
    writeReconnectSecret(localStorage, code, reconnectSecret);
    set({ roomId, code, playerId, reconnectSecret });
  },
  getStoredReconnectSecret: (code) => readReconnectSecret(localStorage, code),
  clearStoredReconnectSecret: (code) => {
    clearReconnectSecret(localStorage, code);
    set({ playerId: null, reconnectSecret: null, roomId: null, code: null });
  },
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
      roomState: payload.state,
      finalScores: payload.lastGameScores?.length
        ? payload.lastGameScores
        : payload.state === "playing" ? null : state.finalScores,
      drawingRecap: payload.lastGameDrawings ?? state.drawingRecap,
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
  startDrawing: ({ drawerId, maskedWord, roundNumber, totalRounds, seconds, hintCost, letterPrices }) =>
    set({
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
    }),
  setMyWord: (word) => set({ myWord: word }),
  setGuessedWord: (word) => set({ guessedWord: word }),
  setMaskedWord: (word) => set({ maskedWord: word }),
  setHintRevealed: ({ maskedWord, hintCost, letterPrices }) =>
    set((s) => ({
      maskedWord,
      nextHintCost: hintCost ?? s.nextHintCost,
      letterPrices: letterPrices !== undefined ? letterPrices : s.letterPrices,
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
  reset: () => set({ playerId: null, reconnectSecret: null, roomId: null, code: null, players: [], ...initialGameFields }),
}));
