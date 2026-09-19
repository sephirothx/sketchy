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
  PresenceCause,
  ColorblindSafeSuggestion,
  DrawingReaction,
  DrawingReactionEvent,
  GameEndedPayload,
  GuessBreakdown,
  LastGamePayload,
  RoomStatePayload,
  TurnEndedPayload,
} from "../types";
import { ui } from "../content/ui/index.ts";

let messageSeq = 0;
const nextMessageId = () => `${Date.now()}-${messageSeq++}`;

/** Registers all Socket.IO event listeners exactly once and syncs them into the zustand store. */
export function useGameSocketListeners() {
  useEffect(() => {
    const store = useGameStore;

    // Why the room changed rides its snapshot (#880): a seat coming or going,
    // or a line the room says about itself. Applied after the snapshot, so a
    // line about a seat reads the room it describes.
    const onRoomState = (payload: RoomStatePayload) => {
      store.getState().setRoomState(payload);
      for (const cause of payload.causes ?? []) {
        if ("presence" in cause) onPresence(cause);
        else onChatMessage(cause);
      }
    };

    const onColorblindSafeSuggestion = (payload: ColorblindSafeSuggestion) => {
      store.getState().setColorblindSafeSuggestion(payload);
    };

    const presenceLine = {
      joined: ui.useGameSocketListeners.nicknameJoinedTheRoom,
      reconnected: ui.useGameSocketListeners.playerReconnected,
      disconnected: ui.useGameSocketListeners.playerDisconnected,
    } as const;

    const onPresence = (cause: PresenceCause) => {
      if (cause.presence === "joined" || cause.presence === "reconnected") playPlayerJoinSound();
      else playPlayerLeaveSound();
      // A seat leaving is a sound only, as it always was.
      if (cause.presence === "left") return;
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: presenceLine[cause.presence]({ nickname: cause.nickname }),
        correct: false,
        system: true,
      });
    };

    // Said by the game's first `turn_starting` (#880), before its own line.
    const onGameStarted = () => {
      // The last game's recap tallies belong to the last game.
      store.getState().clearDrawingReactions();
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: ui.useGameSocketListeners.gameStarted,
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
      gameStarted?: boolean;
    }) => {
      if (payload.gameStarted) onGameStarted();
      playRoundStartSound();
      store.getState().startChoosing(payload);
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: ui.useGameSocketListeners.drawerNicknameIsChoosingAPrompt({ drawerNickname: payload.drawerNickname }),
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
      turnId?: string;
      reactions?: DrawingReaction[];
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
      store.getState().recordCorrectGuess(payload.playerId);
      const elapsed = store.getState().turnCorrectGuesses[payload.playerId];
      const time = elapsed != null
        ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`
        : null;
      const points = store.getState().scoringMode !== "none" ? payload.points : null;
      // `correct` styles the line as the green got-it event card.
      store.getState().addMessage({
        id: nextMessageId(),
        nickname: "",
        text: ui.useGameSocketListeners.gotIt({ nickname: payload.nickname, time, points }),
        correct: true,
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
        text: ui.useGameSocketListeners.thePromptWasPrompt({ prompt: payload.prompt }),
        correct: false,
        system: true,
      });
    };

    const onGameEnded = (payload: GameEndedPayload) => {
      triggerConfettiShower();
      store.getState().endGame(payload);
    };

    const onLastGame = (payload: LastGamePayload) => {
      store.getState().applyLastGame(payload);
    };

    const onDrawingReaction = (payload: DrawingReactionEvent) => {
      store.getState().applyDrawingReaction(payload);
    };

    const onSyncGame = (payload: {
      phase: string;
      turnId?: string;
      reactions?: DrawingReaction[];
      drawerId: string | null;
      maskedPrompt: string;
      roundNumber: number;
      totalRounds: number;
      remainingSeconds: number;
      hintCost?: number | null;
      letterPrices?: Record<string, number> | null;
      hintSpend?: number;
      maxHintSpend?: number;
      correctGuessers?: [string, number][];
      guessed?: (GuessBreakdown & { prompt: string }) | null;
    }) => {
      if (payload.phase === "choosing_prompt") {
        store.getState().startChoosing({
          drawerId: payload.drawerId || "",
          roundNumber: payload.roundNumber,
          totalRounds: payload.totalRounds,
          seconds: payload.remainingSeconds,
          isSync: true,
        });
      } else if (payload.phase === "drawing") {
        store.getState().startDrawing({
          turnId: payload.turnId,
          reactions: payload.reactions,
          drawerId: payload.drawerId || "",
          maskedPrompt: payload.maskedPrompt,
          roundNumber: payload.roundNumber,
          totalRounds: payload.totalRounds,
          seconds: payload.remainingSeconds,
          isSync: true,
          hintCost: payload.hintCost,
          letterPrices: payload.letterPrices,
          hintSpend: payload.hintSpend,
          maxHintSpend: payload.maxHintSpend,
          correctGuessers: payload.correctGuessers,
          guessed: payload.guessed,
        });
      }
    };

    socket.on("room_state", onRoomState);
    socket.on("colorblind_safe_suggestion", onColorblindSafeSuggestion);
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
    socket.on("last_game", onLastGame);
    socket.on("sync_game", onSyncGame);
    socket.on("drawing_reaction", onDrawingReaction);

    return () => {
      socket.off("room_state", onRoomState);
      socket.off("colorblind_safe_suggestion", onColorblindSafeSuggestion);
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
      socket.off("last_game", onLastGame);
      socket.off("sync_game", onSyncGame);
      socket.off("drawing_reaction", onDrawingReaction);
    };
  }, []);
}
