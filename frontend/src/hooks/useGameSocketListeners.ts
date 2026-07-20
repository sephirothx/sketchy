import { useEffect } from "react";
import { socket } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
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

    const onPlayerJoined = (payload: { token: string; nickname: string }) => {
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} joined the room`,
        correct: false,
        system: true,
      });
    };

    const onPlayerReconnected = (payload: { token: string; nickname: string }) => {
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} reconnected`,
        correct: false,
        system: true,
      });
    };

    const onPlayerDisconnected = (payload: { token: string; nickname: string }) => {
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} disconnected`,
        correct: false,
        system: true,
      });
    };

    const onPlayerLeft = () => {
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
      drawerToken: string;
      drawerNickname: string;
      roundNumber: number;
      totalRounds: number;
      seconds: number;
    }) => {
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
      drawerToken: string;
      maskedWord: string;
      roundNumber: number;
      totalRounds: number;
      seconds: number;
    }) => {
      store.getState().startDrawing(payload);
    };

    const onChatMessage = (payload: ChatMessage) => {
      store.getState().addMessage({ ...payload, id: nextMessageId() });
    };

    const onCorrectGuess = (payload: { token: string; nickname: string; points: number }) => {
      store.getState().applyGuessPoints(payload.token, payload.points);
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: `${payload.nickname} guessed the word! (+${payload.points})`,
        correct: false,
        system: true,
      });
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
      store.getState().endGame(payload);
    };

    const onSyncGame = (payload: {
      phase: string;
      drawerToken: string | null;
      maskedWord: string;
      roundNumber: number;
      totalRounds: number;
      remainingSeconds: number;
    }) => {
      if (payload.phase === "drawing" || payload.phase === "choosing_word") {
        store.getState().startDrawing({
          drawerToken: payload.drawerToken || "",
          maskedWord: payload.maskedWord,
          roundNumber: payload.roundNumber,
          totalRounds: payload.totalRounds,
          seconds: payload.remainingSeconds,
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
      socket.off("round_ended", onRoundEnded);
      socket.off("game_ended", onGameEnded);
      socket.off("sync_game", onSyncGame);
    };
  }, []);
}
