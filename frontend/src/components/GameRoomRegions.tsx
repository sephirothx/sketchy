import type { RefObject } from "react";
import { Canvas, type CanvasRef } from "./Canvas";
import { ChoosingPromptOverlay } from "./ChoosingPromptOverlay";
import { GameAnnouncer } from "./GameAnnouncer";
import { RoomChatPanel } from "./RoomChatPanel";
import { RoomPlayersPanel } from "./RoomPlayersPanel";
import { TurnResultsOverlay } from "./TurnResultsOverlay";
import { Timer } from "./Timer";
import { Toolbar } from "./Toolbar";
import { WaitingRoomPanel } from "./WaitingRoomPanel";
import { PromptDisplay } from "./PromptDisplay";
import { useToolbarState } from "../hooks/useToolbarState";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { splitMaskedPrompt } from "../lib/maskedPrompt";
import { recordRender } from "../lib/renderDiagnostics";
import { selectAmDrawer, selectMe, useGameStore } from "../store/gameStore";
import type { RoomShellMode } from "./RoomShell";

export function ConnectedRoomPlayersPanel({ mode }: { mode: RoomShellMode }) {
  const players = useGameStore((state) => state.players);
  const drawerId = useGameStore((state) => state.drawerId);
  const myPlayerId = useGameStore((state) => state.playerId);
  const maxPlayers = useGameStore((state) => state.maxPlayers);
  const showScores = useGameStore((state) => state.scoringMode !== "none");
  const finalScores = useGameStore((state) => state.finalScores);
  const moderation = useGameStore((state) => state.moderation);
  const turnCorrectGuesses = useGameStore((state) => state.turnCorrectGuesses);

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
      turnCorrectGuesses={turnCorrectGuesses}
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
  const myPlayerId = useGameStore((state) => state.playerId);
  const guessedPrompt = useGameStore((state) => state.guessedPrompt);
  const maskedPrompt = useGameStore((state) => state.maskedPrompt);
  const hideMaskedPrompt = useGameStore((state) => state.hideMaskedPrompt);
  const me = players.find((player) => player.playerId === myPlayerId);
  const isDrawer = useGameStore(selectAmDrawer);
  const canGuess =
    phase === "drawing" && !isDrawer && !me?.isSpectator && !guessedPrompt;

  return (
    <RoomChatPanel
      messages={messages}
      players={players}
      mode={mode}
      isDrawer={isDrawer}
      canGuess={canGuess}
      myPlayerId={myPlayerId}
      targetPromptLengths={splitMaskedPrompt(maskedPrompt).counts}
      hideMaskedPrompt={hideMaskedPrompt}
      onFocusChange={onFocusChange}
    />
  );
}

interface ConnectedWaitingRoomPanelProps {
  drawingCount: number;
  highlightCount: number;
  finalScores: ReturnType<typeof useGameStore.getState>["finalScores"];
  onStart: () => void;
  onViewDrawings: () => void;
  onViewHighlights: () => void;
  startBusy: boolean;
  startError: string | null;
}

export function ConnectedWaitingRoomPanel({
  drawingCount,
  highlightCount,
  finalScores,
  onStart,
  onViewDrawings,
  onViewHighlights,
  startBusy,
  startError,
}: ConnectedWaitingRoomPanelProps) {
  const name = useGameStore((state) => state.name);
  const code = useGameStore((state) => state.code);
  const maxPlayers = useGameStore((state) => state.maxPlayers);
  const isPublic = useGameStore((state) => state.isPublic);
  const rounds = useGameStore((state) => state.rounds);
  const drawingSeconds = useGameStore((state) => state.drawingSeconds);
  const customPromptCount = useGameStore((state) => state.customPromptCount);
  const customPromptsOnly = useGameStore((state) => state.customPromptsOnly);
  const hintMode = useGameStore((state) => state.hintMode);
  const scoringMode = useGameStore((state) => state.scoringMode);
  const spectatorsSeePrompt = useGameStore((state) => state.spectatorsSeePrompt);
  const hideMaskedPrompt = useGameStore((state) => state.hideMaskedPrompt);
  const allowedTools = useGameStore((state) => state.allowedTools);
  const colorMode = useGameStore((state) => state.colorMode);
  const promptListSlugs = useGameStore((state) => state.promptListSlugs);
  const players = useGameStore((state) => state.players);
  const myPlayerId = useGameStore((state) => state.playerId);
  const isHost = useGameStore((state) => selectMe(state)?.isHost ?? false);

  return (
    <WaitingRoomPanel
      name={name}
      code={code}
      maxPlayers={maxPlayers}
      isPublic={isPublic}
      rounds={rounds}
      drawingSeconds={drawingSeconds}
      customPromptCount={customPromptCount}
      customPromptsOnly={customPromptsOnly}
      hintMode={hintMode}
      scoringMode={scoringMode}
      spectatorsSeePrompt={spectatorsSeePrompt}
      hideMaskedPrompt={hideMaskedPrompt}
      allowedTools={allowedTools}
      colorMode={colorMode}
      promptListSlugs={promptListSlugs}
      players={players}
      myPlayerId={myPlayerId}
      isHost={isHost}
      finalScores={finalScores}
      startBusy={startBusy}
      startError={startError}
      onStart={onStart}
      drawingCount={drawingCount}
      onViewDrawings={onViewDrawings}
      highlightCount={highlightCount}
      onViewHighlights={onViewHighlights}
    />
  );
}

export function GameplayRegion({ canvasRef }: { canvasRef: RefObject<CanvasRef | null> }) {
  recordRender("gameplay");
  const isMobile = useMediaQuery("(max-width: 900px)");
  const playerId = useGameStore((state) => state.playerId);
  const phase = useGameStore((state) => state.phase);
  const drawerId = useGameStore((state) => state.drawerId);
  const maskedPrompt = useGameStore((state) => state.maskedPrompt);
  const hintMode = useGameStore((state) => state.hintMode);
  const scoringMode = useGameStore((state) => state.scoringMode);
  const nextHintCost = useGameStore((state) => state.nextHintCost);
  const letterPrices = useGameStore((state) => state.letterPrices);
  const hintSpend = useGameStore((state) => state.hintSpend);
  const maxHintSpend = useGameStore((state) => state.maxHintSpend);
  const lastGuessBreakdown = useGameStore((state) => state.lastGuessBreakdown);
  const myPrompt = useGameStore((state) => state.myPrompt);
  const guessedPrompt = useGameStore((state) => state.guessedPrompt);
  const promptChoices = useGameStore((state) => state.promptChoices);
  const roundNumber = useGameStore((state) => state.roundNumber);
  const totalRounds = useGameStore((state) => state.totalRounds);
  const phaseSeconds = useGameStore((state) => state.phaseSeconds);
  const phaseStartedAt = useGameStore((state) => state.phaseStartedAt);
  const lastTurnResult = useGameStore((state) => state.lastTurnResult);
  const spectatorsSeePrompt = useGameStore((state) => state.spectatorsSeePrompt);
  const me = useGameStore(selectMe);
  const drawerNickname = useGameStore((state) =>
    state.players.find((player) => player.playerId === state.drawerId)?.nickname,
  );
  const drawerNameColor = useGameStore((state) =>
    state.players.find((player) => player.playerId === state.drawerId)?.nameColor,
  );

  const amDrawer = useGameStore(selectAmDrawer);
  const canDrawNow = phase === "drawing" && drawerId === playerId;
  const isDrawerPerson = drawerId === playerId;
  const drawerPrompt =
    myPrompt ||
    (maskedPrompt && !maskedPrompt.includes("_")
      ? splitMaskedPrompt(maskedPrompt).blanks.trim()
      : null);
  const downloadPrompt =
    phase === "turn_results"
      ? lastTurnResult?.prompt ?? null
      : isDrawerPerson && phase === "drawing"
        ? drawerPrompt
        : guessedPrompt
          ? guessedPrompt
          : me?.isSpectator &&
              spectatorsSeePrompt &&
              maskedPrompt &&
              !maskedPrompt.includes("_")
            ? splitMaskedPrompt(maskedPrompt).blanks.trim()
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
      {/* Desktop shows the round chip and countdown ring in the room header
          (GameHeaderStatus); this compact line covers mobile, where the header
          hides in guess-focused mode. */}
      {isMobile && (
        <div className="round-info">
          <span>
            Round {roundNumber} of {totalRounds}
          </span>
          {phase !== "turn_results" && (
            <Timer totalSeconds={phaseSeconds} startedAt={phaseStartedAt} variant="text" />
          )}
        </div>
      )}
      <PromptDisplay
        isDrawer={amDrawer}
        myPrompt={myPrompt}
        maskedPrompt={maskedPrompt}
        promptChoices={promptChoices}
        revealedPrompt={phase === "turn_results" ? lastTurnResult?.prompt ?? null : guessedPrompt}
        hintMode={hintMode}
        canBuyHint={phase === "drawing" && !amDrawer && !guessedPrompt}
        nextHintCost={nextHintCost}
        letterPrices={letterPrices}
        hintSpend={hintSpend}
        maxHintSpend={maxHintSpend}
      />
      <Canvas
        ref={canvasRef}
        isDrawer={canDrawNow}
        color={color}
        brushWidth={brushWidth}
        tool={tool}
        downloadPrompt={downloadPrompt}
        label={canvasLabel}
        overlay={
          phase === "choosing_prompt" && !amDrawer ? (
            <ChoosingPromptOverlay
              drawerNickname={drawerNickname || "The next player"}
              drawerNameColor={drawerNameColor}
            />
          ) : null
        }
      />
      {phase === "turn_results" && lastTurnResult && (
        <TurnResultsOverlay
          prompt={lastTurnResult.prompt}
          drawerId={lastTurnResult.drawerId}
          drawerBonus={lastTurnResult.drawerBonus}
          guesses={lastTurnResult.guesses}
          scores={lastTurnResult.scores}
          myPlayerId={playerId}
          showScores={scoringMode !== "none"}
          myBreakdown={lastGuessBreakdown}
          nextTurnSeconds={phaseSeconds}
          nextTurnStartedAt={phaseStartedAt}
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
