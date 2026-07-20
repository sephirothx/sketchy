import { create } from "zustand";
import type {
  ChatMessage,
  GameEndedPayload,
  GamePhase,
  PlayerInfo,
  RoomStatePayload,
  RoundEndedPayload,
} from "../types";

interface GameStore {
  nickname: string;
  token: string | null;
  roomId: string | null;
  code: string | null;
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  roomState: "waiting" | "playing";
  players: PlayerInfo[];

  phase: GamePhase;
  drawerToken: string | null;
  maskedWord: string;
  myWord: string | null;
  wordChoices: string[];
  roundNumber: number;
  totalRounds: number;
  phaseSeconds: number;
  phaseStartedAt: number;

  messages: ChatMessage[];
  lastRoundResult: RoundEndedPayload | null;
  finalScores: GameEndedPayload["scores"] | null;
  error: string | null;

  setNickname: (nickname: string) => void;
  setSession: (session: { roomId: string; code: string; token: string }) => void;
  getStoredToken: (code: string) => string | null;
  setRoomState: (payload: RoomStatePayload) => void;
  addMessage: (message: ChatMessage) => void;
  applyGuessPoints: (token: string, points: number) => void;
  startChoosing: (payload: {
    drawerToken: string;
    roundNumber: number;
    totalRounds: number;
    seconds: number;
  }) => void;
  setMyWordChoices: (choices: string[], seconds: number) => void;
  startDrawing: (payload: {
    drawerToken: string;
    maskedWord: string;
    roundNumber: number;
    totalRounds: number;
    seconds: number;
  }) => void;
  setMyWord: (word: string | null) => void;
  endRound: (payload: RoundEndedPayload) => void;
  endGame: (payload: GameEndedPayload) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const initialGameFields = {
  phase: "idle" as GamePhase,
  drawerToken: null as string | null,
  maskedWord: "",
  myWord: null as string | null,
  wordChoices: [] as string[],
  roundNumber: 0,
  totalRounds: 0,
  phaseSeconds: 0,
  phaseStartedAt: 0,
  messages: [] as ChatMessage[],
  lastRoundResult: null as RoundEndedPayload | null,
  finalScores: null as GameEndedPayload["scores"] | null,
};

export const useGameStore = create<GameStore>((set) => ({
  nickname: localStorage.getItem("sketchy_nickname") || "",
  token: null,
  roomId: null,
  code: null,
  name: "",
  isPublic: true,
  maxPlayers: 8,
  rounds: 3,
  roomState: "waiting",
  players: [],
  error: null,
  ...initialGameFields,

  setNickname: (nickname) => {
    localStorage.setItem("sketchy_nickname", nickname);
    set({ nickname });
  },
  setSession: ({ roomId, code, token }) => {
    localStorage.setItem(`sketchy_token_${code}`, token);
    set({ roomId, code, token });
  },
  getStoredToken: (code) => localStorage.getItem(`sketchy_token_${code}`),
  setRoomState: (payload) =>
    set({
      roomId: payload.id,
      code: payload.code,
      name: payload.name,
      isPublic: payload.isPublic,
      maxPlayers: payload.maxPlayers,
      rounds: payload.rounds,
      roomState: payload.state,
      players: payload.players,
    }),
  addMessage: (message) => set((s) => ({ messages: [...s.messages.slice(-99), message] })),
  applyGuessPoints: (token, points) =>
    set((s) => ({
      players: s.players.map((p) => (p.token === token ? { ...p, score: p.score + points } : p)),
    })),
  startChoosing: ({ drawerToken, roundNumber, totalRounds, seconds }) =>
    set({
      phase: "choosing_word",
      drawerToken,
      roundNumber,
      totalRounds,
      phaseSeconds: seconds,
      phaseStartedAt: Date.now(),
      maskedWord: "",
      myWord: null,
      wordChoices: [],
      lastRoundResult: null,
    }),
  setMyWordChoices: (choices, seconds) =>
    set({ wordChoices: choices, phaseSeconds: seconds, phaseStartedAt: Date.now() }),
  startDrawing: ({ drawerToken, maskedWord, roundNumber, totalRounds, seconds }) =>
    set({
      phase: "drawing",
      drawerToken,
      maskedWord,
      roundNumber,
      totalRounds,
      phaseSeconds: seconds,
      phaseStartedAt: Date.now(),
      wordChoices: [],
    }),
  setMyWord: (word) => set({ myWord: word }),
  endRound: (payload) =>
    set((s) => ({
      phase: "round_end",
      lastRoundResult: payload,
      players: s.players.map((p) => {
        const updated = payload.scores.find((sc) => sc.token === p.token);
        return updated ? { ...p, score: updated.score } : p;
      }),
    })),
  endGame: (payload) => set({ phase: "game_end", finalScores: payload.scores, roomState: "waiting" }),
  setError: (error) => set({ error }),
  reset: () => set({ token: null, roomId: null, code: null, players: [], ...initialGameFields }),
}));
