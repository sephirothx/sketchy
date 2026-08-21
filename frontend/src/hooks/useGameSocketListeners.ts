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
  TurnEndedPayload,
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
        text: `${payload.drawerNickname} is choosing a prompt...`,
        correct: false,
        system: true,
      });
    };

    const onYourPromptChoices = (payload: { choices: string[]; seconds: number }) => {
      store.getState().setMyPromptChoices(payload.choices, payload.seconds);
    };

    const onYouAreDrawing = (payload: { prompt: string; choices?: string[] }) => {
      store.getState().setMyPrompt(payload.prompt);
    };

    const onTurnStarted = (payload: {
      drawerId: string;
      maskedPrompt: string;
      roundNumber: number;
      totalRounds: number;
      seconds: number;
      hintCost?: number | null;
      letterPrices?: Record<string, number> | null;
      hintSpend?: number;
      maxHintSpend?: number;
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
        store.getState().scoringMode !== "none" ? ` (+${payload.points})` : "";
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} guessed the prompt!${pointsSuffix}`,
        correct: false,
        system: true,
      });
    };

    const onYouGuessedCorrectly = (payload: {
      prompt: string;
      points?: number;
      basePoints?: number;
      hintSpend?: number;
    }) => {
      triggerConfettiBurst();
      playMyCorrectGuessSound();
      store.getState().setGuessedPrompt(
        payload.prompt,
        payload.basePoints === undefined
          ? null
          : {
              points: payload.points ?? 0,
              basePoints: payload.basePoints,
              hintSpend: payload.hintSpend ?? 0,
            },
      );
    };

    const onHintRevealed = (payload: {
      maskedPrompt: string;
      hintCost?: number | null;
      letterPrices?: Record<string, number> | null;
      hintSpend?: number;
    }) => {
      store.getState().setHintRevealed(payload);
    };

    const onTurnEnded = (payload: TurnEndedPayload) => {
      store.getState().endTurn(payload);
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `The prompt was "${payload.prompt}"`,
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
      maskedPrompt: string;
      roundNumber: number;
      totalRounds: number;
      remainingSeconds: number;
      hintCost?: number | null;
      letterPrices?: Record<string, number> | null;
      hintSpend?: number;
      maxHintSpend?: number;
    }) => {
      if (payload.phase === "choosing_prompt") {
        store.getState().startChoosing({
          drawerId: payload.drawerId || "",
          roundNumber: payload.roundNumber,
          totalRounds: payload.totalRounds,
          seconds: payload.remainingSeconds,
        });
      } else if (payload.phase === "drawing") {
        store.getState().startDrawing({
          drawerId: payload.drawerId || "",
          maskedPrompt: payload.maskedPrompt,
          roundNumber: payload.roundNumber,
          totalRounds: payload.totalRounds,
          seconds: payload.remainingSeconds,
          hintCost: payload.hintCost,
          letterPrices: payload.letterPrices,
          hintSpend: payload.hintSpend,
          maxHintSpend: payload.maxHintSpend,
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
    socket.on("your_prompt_choices", onYourPromptChoices);
    socket.on("you_are_drawing", onYouAreDrawing);
    socket.on("turn_started", onTurnStarted);
    socket.on("chat_message", onChatMessage);
    socket.on("correct_guess", onCorrectGuess);
    socket.on("you_guessed_correctly", onYouGuessedCorrectly);
    socket.on("hint_revealed", onHintRevealed);
    socket.on("turn_ended", onTurnEnded);
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
      socket.off("your_prompt_choices", onYourPromptChoices);
      socket.off("you_are_drawing", onYouAreDrawing);
      socket.off("turn_started", onTurnStarted);
      socket.off("chat_message", onChatMessage);
      socket.off("correct_guess", onCorrectGuess);
      socket.off("you_guessed_correctly", onYouGuessedCorrectly);
      socket.off("hint_revealed", onHintRevealed);
      socket.off("turn_ended", onTurnEnded);
      socket.off("game_ended", onGameEnded);
      socket.off("sync_game", onSyncGame);
    };
  }, []);
}
