import type { RefObject } from "react";
import { Canvas, type CanvasRef } from "./Canvas";
import { ChoosingWordOverlay } from "./ChoosingWordOverlay";
import { GameAnnouncer } from "./GameAnnouncer";
import { RoomChatPanel } from "./RoomChatPanel";
import { RoomPlayersPanel } from "./RoomPlayersPanel";
import { RoundEndOverlay } from "./RoundEndOverlay";
import { Timer } from "./Timer";
import { Toolbar } from "./Toolbar";
import { WaitingRoomPanel } from "./WaitingRoomPanel";
import { WordDisplay } from "./WordDisplay";
import { useToolbarState } from "../hooks/useToolbarState";
import { splitMaskedWord } from "../lib/maskedWord";
import { recordRender } from "../lib/renderDiagnostics";
import { useGameStore } from "../store/gameStore";
import type { RoomShellMode } from "./RoomShell";

export function ConnectedRoomPlayersPanel({ mode }: { mode: RoomShellMode }) {
  const players = useGameStore((state) => state.players);
  const drawerId = useGameStore((state) => state.drawerId);
  const myPlayerId = useGameStore((state) => state.playerId);
  const maxPlayers = useGameStore((state) => state.maxPlayers);
  const showScores = useGameStore((state) => state.scoringMode !== "none");
  const finalScores = useGameStore((state) => state.finalScores);
  const moderation = useGameStore((state) => state.moderation);

  return (
    <RoomPlayersPanel
      mode={mode}
      players={players}
      drawerId={drawerId}
      myPlayerId={myPlayerId}
      maxPlayers={maxPlayers}
      showScores={showScores}
      finalScores={finalScores}
      moderation={moderation}
    />
  );
}

interface ConnectedRoomChatPanelProps {
  mode: RoomShellMode;
  onFocusChange: (focused: boolean) => void;
}

export function ConnectedRoomChatPanel({
  mode,
  onFocusChange,
}: ConnectedRoomChatPanelProps) {
  const messages = useGameStore((state) => state.messages);
  const players = useGameStore((state) => state.players);
  const phase = useGameStore((state) => state.phase);
  const drawerId = useGameStore((state) => state.drawerId);
  const myPlayerId = useGameStore((state) => state.playerId);
  const guessedWord = useGameStore((state) => state.guessedWord);
  const maskedWord = useGameStore((state) => state.maskedWord);
  const hideMaskedPrompt = useGameStore((state) => state.hideMaskedPrompt);
  const me = players.find((player) => player.playerId === myPlayerId);
  const isDrawer =
    (phase === "drawing" || phase === "choosing_word") && drawerId === myPlayerId;
  const canGuess =
    phase === "drawing" && !isDrawer && !me?.isSpectator && !guessedWord;

  return (
    <RoomChatPanel
      messages={messages}
      players={players}
      mode={mode}
      isDrawer={isDrawer}
      canGuess={canGuess}
      myPlayerId={myPlayerId}
      targetWordLengths={splitMaskedWord(maskedWord).counts}
      hideMaskedPrompt={hideMaskedPrompt}
      onFocusChange={onFocusChange}
    />
  );
}

interface ConnectedWaitingRoomPanelProps {
  drawingCount: number;
  finalScores: ReturnType<typeof useGameStore.getState>["finalScores"];
  onStart: () => void;
  onViewDrawings: () => void;
  startBusy: boolean;
  startError: string | null;
}

export function ConnectedWaitingRoomPanel({
  drawingCount,
  finalScores,
  onStart,
  onViewDrawings,
  startBusy,
  startError,
}: ConnectedWaitingRoomPanelProps) {
  const name = useGameStore((state) => state.name);
  const isPublic = useGameStore((state) => state.isPublic);
  const rounds = useGameStore((state) => state.rounds);
  const drawingSeconds = useGameStore((state) => state.drawingSeconds);
  const customWordCount = useGameStore((state) => state.customWordCount);
  const customWordsOnly = useGameStore((state) => state.customWordsOnly);
  const hintMode = useGameStore((state) => state.hintMode);
  const scoringMode = useGameStore((state) => state.scoringMode);
  const spectatorsSeeSolution = useGameStore((state) => state.spectatorsSeeSolution);
  const hideMaskedPrompt = useGameStore((state) => state.hideMaskedPrompt);
  const wordListSlugs = useGameStore((state) => state.wordListSlugs);
  const players = useGameStore((state) => state.players);
  const myPlayerId = useGameStore((state) => state.playerId);
  const isHost = useGameStore((state) =>
    state.players.find((player) => player.playerId === state.playerId)?.isHost ?? false,
  );

  return (
    <WaitingRoomPanel
      name={name}
      isPublic={isPublic}
      rounds={rounds}
      drawingSeconds={drawingSeconds}
      customWordCount={customWordCount}
      customWordsOnly={customWordsOnly}
      hintMode={hintMode}
      scoringMode={scoringMode}
      spectatorsSeeSolution={spectatorsSeeSolution}
      hideMaskedPrompt={hideMaskedPrompt}
      wordListSlugs={wordListSlugs}
      players={players}
      myPlayerId={myPlayerId}
      isHost={isHost}
      finalScores={finalScores}
      startBusy={startBusy}
      startError={startError}
      onStart={onStart}
      drawingCount={drawingCount}
      onViewDrawings={onViewDrawings}
    />
  );
}

export function GameplayRegion({ canvasRef }: { canvasRef: RefObject<CanvasRef | null> }) {
  recordRender("gameplay");
  const playerId = useGameStore((state) => state.playerId);
  const phase = useGameStore((state) => state.phase);
  const drawerId = useGameStore((state) => state.drawerId);
  const maskedWord = useGameStore((state) => state.maskedWord);
  const hintMode = useGameStore((state) => state.hintMode);
  const scoringMode = useGameStore((state) => state.scoringMode);
  const nextHintCost = useGameStore((state) => state.nextHintCost);
  const letterPrices = useGameStore((state) => state.letterPrices);
  const myWord = useGameStore((state) => state.myWord);
  const guessedWord = useGameStore((state) => state.guessedWord);
  const wordChoices = useGameStore((state) => state.wordChoices);
  const roundNumber = useGameStore((state) => state.roundNumber);
  const totalRounds = useGameStore((state) => state.totalRounds);
  const phaseSeconds = useGameStore((state) => state.phaseSeconds);
  const phaseStartedAt = useGameStore((state) => state.phaseStartedAt);
  const lastRoundResult = useGameStore((state) => state.lastRoundResult);
  const spectatorsSeeSolution = useGameStore((state) => state.spectatorsSeeSolution);
  const me = useGameStore((state) =>
    state.players.find((player) => player.playerId === state.playerId),
  );
  const drawerNickname = useGameStore((state) =>
    state.players.find((player) => player.playerId === state.drawerId)?.nickname,
  );
  const drawerNameColor = useGameStore((state) =>
    state.players.find((player) => player.playerId === state.drawerId)?.nameColor,
  );

  const amDrawer =
    (phase === "drawing" || phase === "choosing_word") && drawerId === playerId;
  const canDrawNow = phase === "drawing" && drawerId === playerId;
  const isDrawerPerson = drawerId === playerId;
  const drawerWord =
    myWord ||
    (maskedWord && !maskedWord.includes("_")
      ? splitMaskedWord(maskedWord).blanks.trim()
      : null);
  const solutionWord =
    phase === "round_end"
      ? lastRoundResult?.word ?? null
      : isDrawerPerson && phase === "drawing"
        ? drawerWord
        : guessedWord
          ? guessedWord
          : me?.isSpectator &&
              spectatorsSeeSolution &&
              maskedWord &&
              !maskedWord.includes("_")
            ? splitMaskedWord(maskedWord).blanks.trim()
            : null;
  const {
    color,
    setColor,
    brushWidth,
    onBrushWidthChange,
    tool,
    setTool,
  } = useToolbarState(amDrawer);

  const canvasLabel = canDrawNow
    ? "Drawing canvas. You are drawing."
    : me?.isSpectator
      ? `Drawing canvas. Spectating ${drawerNickname || "the drawer"}.`
      : `Drawing canvas. ${drawerNickname || "A player"} is drawing.`;

  const phaseAnnouncement = phase === "drawing"
    ? (canDrawNow
      ? "Your turn to draw."
      : `${drawerNickname || "A player"} is drawing.`)
    : "";

  return (
    <main className="canvas-area">
      <GameAnnouncer message={phaseAnnouncement} />
      <div className="round-info">
        <span>
          Round {roundNumber}/{totalRounds}
        </span>
        {phase !== "round_end" && (
          <Timer totalSeconds={phaseSeconds} startedAt={phaseStartedAt} />
        )}
      </div>
      <WordDisplay
        isDrawer={amDrawer}
        myWord={myWord}
        maskedWord={maskedWord}
        wordChoices={wordChoices}
        revealedWord={phase === "round_end" ? lastRoundResult?.word ?? null : guessedWord}
        hintMode={hintMode}
        canBuyHint={phase === "drawing" && !amDrawer && !guessedWord}
        myScore={me?.score ?? 0}
        nextHintCost={nextHintCost}
        letterPrices={letterPrices}
      />
      <Canvas
        ref={canvasRef}
        isDrawer={canDrawNow}
        color={color}
        brushWidth={brushWidth}
        tool={tool}
        solutionWord={solutionWord}
        label={canvasLabel}
        overlay={
          phase === "choosing_word" && !amDrawer ? (
            <ChoosingWordOverlay
              drawerNickname={drawerNickname || "The next player"}
              drawerNameColor={drawerNameColor}
            />
          ) : null
        }
      />
      {phase === "round_end" && lastRoundResult && (
        <RoundEndOverlay
          word={lastRoundResult.word}
          drawerId={lastRoundResult.drawerId}
          drawerBonus={lastRoundResult.drawerBonus}
          guesses={lastRoundResult.guesses}
          scores={lastRoundResult.scores}
          myPlayerId={playerId}
          showScores={scoringMode !== "none"}
        />
      )}
      {canDrawNow && (
        <Toolbar
          color={color}
          onColorChange={setColor}
          brushWidth={brushWidth}
          onBrushWidthChange={onBrushWidthChange}
          tool={tool}
          onToolChange={setTool}
        />
      )}
    </main>
  );
}
