import { useEffect } from "react";
import { socket } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { triggerConfettiBurst, triggerConfettiShower } from "../lib/confetti";
import {
  playCloseGuessSound,
  playCorrectGuessSound,
  playMyCorrectGuessSound,
  playPlayerJoinSound,
  playPlayerLeaveSound,
  playRoundStartSound,
} from "../lib/sound";
import type {
  ChatMessage,
  GameEndedPayload,
  RoomStatePayload,
  RoundEndedPayload,
} from "../types";

let messageSeq = 0;
const nextMessageId = () => `${Date.now()}-${messageSeq++}`;

/** Registers all Socket.IO event listeners exactly once and syncs them into the zustand store. */
export function useGameSocketListeners() {
  useEffect(() => {
    const store = useGameStore;

    const onRoomState = (payload: RoomStatePayload) => store.getState().setRoomState(payload);

    const onPlayerJoined = (payload: { playerId: string; nickname: string }) => {
      playPlayerJoinSound();
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} joined the room`,
        correct: false,
        system: true,
      });
    };

    const onPlayerReconnected = (payload: { playerId: string; nickname: string }) => {
      playPlayerJoinSound();
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} reconnected`,
        correct: false,
        system: true,
      });
    };

    const onPlayerDisconnected = (payload: { playerId: string; nickname: string }) => {
      playPlayerLeaveSound();
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} disconnected`,
        correct: false,
        system: true,
      });
    };

    const onPlayerLeft = () => {
      playPlayerLeaveSound();
      // room_state is re-emitted by the server right after, so no local patch needed here.
    };

    const onGameStarted = () => {
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: "Game started!",
        correct: false,
        system: true,
      });
    };

    const onTurnStarting = (payload: {
      drawerId: string;
      drawerNickname: string;
      roundNumber: number;
      totalRounds: number;
      seconds: number;
    }) => {
      playRoundStartSound();
      store.getState().startChoosing(payload);
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.drawerNickname} is choosing a word...`,
        correct: false,
        system: true,
      });
    };

    const onYourWordChoices = (payload: { choices: string[]; seconds: number }) => {
      store.getState().setMyWordChoices(payload.choices, payload.seconds);
    };

    const onYouAreDrawing = (payload: { word: string; choices?: string[] }) => {
      store.getState().setMyWord(payload.word);
    };

    const onTurnStarted = (payload: {
      drawerId: string;
      maskedWord: string;
      roundNumber: number;
      totalRounds: number;
      seconds: number;
      hintCost?: number | null;
      letterPrices?: Record<string, number> | null;
    }) => {
      playRoundStartSound();
      store.getState().startDrawing(payload);
    };

    const onChatMessage = (payload: ChatMessage) => {
      if (payload.close) {
        playCloseGuessSound();
      }
      const nameColor = store.getState().players.find(
        (player) => player.playerId === payload.playerId,
      )?.nameColor;
      store.getState().addMessage({
        ...payload,
        nameColor: payload.nameColor ?? nameColor,
        id: nextMessageId(),
      });
    };

    const onCorrectGuess = (payload: { playerId: string; nickname: string; points: number }) => {
      if (payload.playerId !== store.getState().playerId) {
        playCorrectGuessSound();
      }
      store.getState().applyGuessPoints(payload.playerId, payload.points);
      const pointsSuffix =
        store.getState().scoringMode === "default" ? ` (+${payload.points})` : "";
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} guessed the word!${pointsSuffix}`,
        correct: false,
        system: true,
      });
    };

    const onYouGuessedCorrectly = (payload: { word: string }) => {
      triggerConfettiBurst();
      playMyCorrectGuessSound();
      store.getState().setGuessedWord(payload.word);
    };

    const onHintRevealed = (payload: {
      maskedWord: string;
      hintCost?: number | null;
      letterPrices?: Record<string, number> | null;
    }) => {
      store.getState().setHintRevealed(payload);
    };

    const onRoundEnded = (payload: RoundEndedPayload) => {
      store.getState().endRound(payload);
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `The word was "${payload.word}"`,
        correct: false,
        system: true,
      });
    };

    const onGameEnded = (payload: GameEndedPayload) => {
      triggerConfettiShower();
      store.getState().endGame(payload);
    };

    const onSyncGame = (payload: {
      phase: string;
      drawerId: string | null;
      maskedWord: string;
      roundNumber: number;
      totalRounds: number;
      remainingSeconds: number;
      hintCost?: number | null;
      letterPrices?: Record<string, number> | null;
    }) => {
      if (payload.phase === "choosing_word") {
        store.getState().startChoosing({
          drawerId: payload.drawerId || "",
          roundNumber: payload.roundNumber,
          totalRounds: payload.totalRounds,
          seconds: payload.remainingSeconds,
        });
      } else if (payload.phase === "drawing") {
        store.getState().startDrawing({
          drawerId: payload.drawerId || "",
          maskedWord: payload.maskedWord,
          roundNumber: payload.roundNumber,
          totalRounds: payload.totalRounds,
          seconds: payload.remainingSeconds,
          hintCost: payload.hintCost,
          letterPrices: payload.letterPrices,
        });
      }
    };

    socket.on("room_state", onRoomState);
    socket.on("player_joined", onPlayerJoined);
    socket.on("player_reconnected", onPlayerReconnected);
    socket.on("player_disconnected", onPlayerDisconnected);
    socket.on("player_left", onPlayerLeft);
    socket.on("game_started", onGameStarted);
    socket.on("turn_starting", onTurnStarting);
    socket.on("your_word_choices", onYourWordChoices);
    socket.on("you_are_drawing", onYouAreDrawing);
    socket.on("turn_started", onTurnStarted);
    socket.on("chat_message", onChatMessage);
    socket.on("correct_guess", onCorrectGuess);
    socket.on("you_guessed_correctly", onYouGuessedCorrectly);
    socket.on("hint_revealed", onHintRevealed);
    socket.on("round_ended", onRoundEnded);
    socket.on("game_ended", onGameEnded);
    socket.on("sync_game", onSyncGame);

    return () => {
      socket.off("room_state", onRoomState);
      socket.off("player_joined", onPlayerJoined);
      socket.off("player_reconnected", onPlayerReconnected);
      socket.off("player_disconnected", onPlayerDisconnected);
      socket.off("player_left", onPlayerLeft);
      socket.off("game_started", onGameStarted);
      socket.off("turn_starting", onTurnStarting);
      socket.off("your_word_choices", onYourWordChoices);
      socket.off("you_are_drawing", onYouAreDrawing);
      socket.off("turn_started", onTurnStarted);
      socket.off("chat_message", onChatMessage);
      socket.off("correct_guess", onCorrectGuess);
      socket.off("you_guessed_correctly", onYouGuessedCorrectly);
      socket.off("hint_revealed", onHintRevealed);
      socket.off("round_ended", onRoundEnded);
      socket.off("game_ended", onGameEnded);
      socket.off("sync_game", onSyncGame);
    };
  }, []);
}
