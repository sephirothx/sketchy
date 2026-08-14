import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Canvas, type CanvasRef } from "../components/Canvas";
import { Toolbar } from "../components/Toolbar";
import { WordDisplay } from "../components/WordDisplay";
import { Timer } from "../components/Timer";
import { RoundEndOverlay } from "../components/RoundEndOverlay";
import { WaitingRoomPanel } from "../components/WaitingRoomPanel";
import { GameEndOverlay } from "../components/GameEndOverlay";
import { DrawingRecapGallery } from "../components/DrawingRecapGallery";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { ChoosingWordOverlay } from "../components/ChoosingWordOverlay";
import { RoomChatPanel } from "../components/RoomChatPanel";
import { RoomPlayersPanel } from "../components/RoomPlayersPanel";
import { RoomShell, type RoomShellMode } from "../components/RoomShell";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useToolbarState } from "../hooks/useToolbarState";
import { useVisualViewportCssVars } from "../hooks/useVisualViewportCssVars";
import { emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import { splitMaskedWord } from "../lib/maskedWord";
import { SettingsIcon } from "../components/SettingsIcon";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse } from "../types";

export function ActiveGameRoom({ code }: { code: string }) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const openSettings = useSettingsStore((s) => s.openSettings);

  const canvasRef = useRef<CanvasRef | null>(null);
  const exitingRoomRef = useRef(false);

  const playerId = useGameStore((s) => s.playerId);
  const clearStoredReconnectSecret = useGameStore((s) => s.clearStoredReconnectSecret);
  const reset = useGameStore((s) => s.reset);

  const roomState = useGameStore((s) => s.roomState);
  const players = useGameStore((s) => s.players);
  const moderation = useGameStore((s) => s.moderation);
  const phase = useGameStore((s) => s.phase);
  const drawerId = useGameStore((s) => s.drawerId);
  const maskedWord = useGameStore((s) => s.maskedWord);
  const hintMode = useGameStore((s) => s.hintMode);
  const scoringMode = useGameStore((s) => s.scoringMode);
  const name = useGameStore((s) => s.name);
  const isPublic = useGameStore((s) => s.isPublic);
  const maxPlayers = useGameStore((s) => s.maxPlayers);
  const rounds = useGameStore((s) => s.rounds);
  const customWordCount = useGameStore((s) => s.customWordCount);
  const customWordsOnly = useGameStore((s) => s.customWordsOnly);
  const drawingSeconds = useGameStore((s) => s.drawingSeconds);
  const nextHintCost = useGameStore((s) => s.nextHintCost);
  const letterPrices = useGameStore((s) => s.letterPrices);
  const myWord = useGameStore((s) => s.myWord);
  const guessedWord = useGameStore((s) => s.guessedWord);
  const wordChoices = useGameStore((s) => s.wordChoices);
  const roundNumber = useGameStore((s) => s.roundNumber);
  const totalRounds = useGameStore((s) => s.totalRounds);
  const phaseSeconds = useGameStore((s) => s.phaseSeconds);
  const phaseStartedAt = useGameStore((s) => s.phaseStartedAt);
  const messages = useGameStore((s) => s.messages);
  const lastRoundResult = useGameStore((s) => s.lastRoundResult);
  const finalScores = useGameStore((s) => s.finalScores);
  const drawingRecap = useGameStore((s) => s.drawingRecap);
  const dismissGameEnd = useGameStore((s) => s.dismissGameEnd);

  const normalizedCode = code.trim().toUpperCase();
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [leaveConfirmationOpen, setLeaveConfirmationOpen] = useState(false);
  const [startBusy, setStartBusy] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [recapOpen, setRecapOpen] = useState(false);
  const [playersDrawerOpen, setPlayersDrawerOpen] = useState(false);
  const isMobile = useMediaQuery("(max-width: 900px)");

  useVisualViewportCssVars();

  useEffect(() => {
    if (!playersDrawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setPlayersDrawerOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [playersDrawerOpen]);

  useEffect(() => {
    function closeRecapForNewGame() {
      setRecapOpen(false);
    }
    socket.on("game_started", closeRecapForNewGame);
    return () => {
      socket.off("game_started", closeRecapForNewGame);
    };
  }, []);

  async function handleCopyLink() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(window.location.href);
      notify("Invite link copied.", "success", 2500);
    } catch {
      notify("Couldn’t copy the link. Copy it from the address bar.", "error");
    }
  }

  useEffect(() => {
    function onKicked(data: { reason?: string }) {
      exitingRoomRef.current = true;
      clearStoredReconnectSecret(normalizedCode);
      reset();
      navigate("/", { state: { criticalError: data?.reason || "You were kicked from the room." } });
    }
    function onVotedAfk(data: { message?: string }) {
      notify(data?.message || "You were marked AFK by room vote.", "warning");
    }
    socket.on("kicked", onKicked);
    socket.on("voted_afk", onVotedAfk);
    return () => {
      socket.off("kicked", onKicked);
      socket.off("voted_afk", onVotedAfk);
    };
  }, [clearStoredReconnectSecret, navigate, normalizedCode, notify, reset]);

  function performLeave() {
    exitingRoomRef.current = true;
    clearStoredReconnectSecret(normalizedCode);
    socket.emit("leave_room");
    reset();
    navigate("/");
  }

  function handleLeave() {
    if (roomState === "playing") {
      setLeaveConfirmationOpen(true);
      return;
    }
    performLeave();
  }

  function handleToggleAfk() {
    socket.emit("toggle_afk");
  }

  async function handleStartGame() {
    setRecapOpen(false);
    setStartBusy(true);
    setStartError(null);
    try {
      const response = await emitWithAck<AckResponse>("start_game", {});
      if (!response.ok) setStartError(response.error || "Could not start the game. Please try again.");
    } catch (startError) {
      setStartError(socketRequestErrorMessage(startError, "start the game"));
    } finally {
      setStartBusy(false);
    }
  }

  function handleViewDrawingsFromGameEnd() {
    dismissGameEnd();
    setRecapOpen(true);
  }

  const me = players.find((p) => p.playerId === playerId);
  const drawer = players.find((player) => player.playerId === drawerId);
  const isHost = me?.isHost ?? false;
  const amDrawer =
    (phase === "drawing" || phase === "choosing_word") && drawerId === playerId;
  const canDrawNow = phase === "drawing" && drawerId === playerId;
  const canGuess = phase === "drawing" && !amDrawer && !(me?.isSpectator) && !guessedWord;

  // Density mode only: hide chrome while guessing on mobile. Positioning stays on the stable vv-pinned shell.
  const isGuessFocused =
    isInputFocused && canGuess && phase === "drawing" && isMobile;

  if (isInputFocused && (!canGuess || phase !== "drawing")) {
    setIsInputFocused(false);
  }

  const {
    color,
    setColor,
    brushWidth,
    onBrushWidthChange,
    tool,
    setTool,
  } = useToolbarState(amDrawer);

  const spectatorsSeeSolution = useGameStore((s) => s.spectatorsSeeSolution);
  const hideMaskedPrompt = useGameStore((s) => s.hideMaskedPrompt);
  const isDrawerPerson = drawerId === playerId;
  const drawerWord = myWord || (maskedWord && !maskedWord.includes("_") ? splitMaskedWord(maskedWord).blanks.trim() : null);

  const solutionWord =
    phase === "round_end"
      ? lastRoundResult?.word ?? null
      : isDrawerPerson && phase === "drawing"
      ? drawerWord
      : guessedWord
      ? guessedWord
      : me?.isSpectator && spectatorsSeeSolution && maskedWord && !maskedWord.includes("_")
      ? splitMaskedWord(maskedWord).blanks.trim()
      : null;
  const roomView: RoomShellMode =
    phase === "game_end" && finalScores ? "game-end" : roomState;

  if (playersDrawerOpen && (roomView !== "playing" || !isMobile)) {
    setPlayersDrawerOpen(false);
  }

  return (
    <div
      className={`game-room${roomView === "playing" ? " game-room-playing" : ""}${isGuessFocused ? " guess-focused" : ""}`}
    >
      {leaveConfirmationOpen && (
        <ConfirmationDialog
          title={amDrawer ? "Leave during your turn?" : "Leave active game?"}
          description={amDrawer
            ? "You’re the current drawer. Leaving now will interrupt your turn and advance the game for everyone."
            : "The game is still in progress. You’ll leave the room and give up your place in this game."}
          confirmLabel="Leave game"
          onCancel={() => setLeaveConfirmationOpen(false)}
          onConfirm={() => {
            setLeaveConfirmationOpen(false);
            performLeave();
          }}
        />
      )}
      <header className="game-header">
        <div className="game-header-start">
          <button
            type="button"
            className="room-copy-button"
            onClick={() => void handleCopyLink()}
            title="Click to copy room invite link"
          >
            <span>Code: {code}</span>
          </button>
          {roomView === "playing" && isMobile && (
            <button
              type="button"
              className="game-header-players-button"
              onClick={() => setPlayersDrawerOpen(true)}
              aria-label="View players"
              title="View players"
              data-testid="open-players-drawer"
            >
              <span className="header-action-icon" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </span>
              <span className="header-action-label">Players</span>
            </button>
          )}
        </div>
        <div className="game-header-actions">
          <button
            type="button"
            className="game-header-afk-button"
            style={{ background: me?.isAfk ? "#f59e0b" : undefined, color: me?.isAfk ? "#fff" : undefined }}
            onClick={handleToggleAfk}
            aria-label={me?.isAfk ? "Back from AFK" : "Go AFK"}
            title={me?.isAfk ? "Back from AFK" : "Go AFK"}
          >
            <span className="header-action-icon" aria-hidden="true">{me?.isAfk ? "💤" : "AFK"}</span>
            <span className="header-action-label">{me?.isAfk ? "AFK 💤" : "AFK"}</span>
          </button>
          <button
            type="button"
            className="game-header-leave-button"
            onClick={handleLeave}
            aria-label="Leave room"
            title="Leave room"
          >
            <span className="header-action-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </span>
            <span className="header-action-label">Leave</span>
          </button>
          {roomView === "playing" && (
            <button
              type="button"
              className="save-image-button game-header-save-button"
              onClick={() => canvasRef.current?.saveImage()}
              aria-label="Save image"
              title="Save drawn image to file"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span className="header-action-label">Save</span>
            </button>
          )}
          <button
            type="button"
            className="header-settings-button"
            onClick={openSettings}
            title="Game Settings"
            aria-label="Game Settings"
          >
            <SettingsIcon size={16} />
            <span className="header-action-label">Settings</span>
          </button>
        </div>
      </header>

      {playersDrawerOpen && (
        <div
          className="players-drawer-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPlayersDrawerOpen(false);
          }}
        >
          <aside
            className="players-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Players in room"
            data-testid="players-drawer"
          >
            <div className="players-drawer-header">
              <h2>Players</h2>
              <button
                type="button"
                className="players-drawer-close"
                onClick={() => setPlayersDrawerOpen(false)}
                aria-label="Close players"
              >
                ✕
              </button>
            </div>
            <div className="players-drawer-body sidebar-box">
              <RoomPlayersPanel
                mode={roomView}
                players={players}
                drawerId={drawerId}
                myPlayerId={playerId}
                maxPlayers={maxPlayers}
                showScores={scoringMode === "default"}
                finalScores={finalScores}
                moderation={moderation}
              />
            </div>
          </aside>
        </div>
      )}

      <RoomShell
        mode={roomView}
        players={
          <RoomPlayersPanel
            mode={roomView}
            players={players}
            drawerId={drawerId}
            myPlayerId={playerId}
            maxPlayers={maxPlayers}
            showScores={scoringMode === "default"}
            finalScores={finalScores}
            moderation={moderation}
          />
        }
        main={
          recapOpen && drawingRecap.length > 0 ? (
            <DrawingRecapGallery
              entries={drawingRecap}
              onClose={() => setRecapOpen(false)}
            />
          ) : roomView === "game-end" && finalScores ? (
            <GameEndOverlay
              scores={finalScores}
              myPlayerId={playerId}
              scoringMode={scoringMode}
              onContinue={dismissGameEnd}
              drawingCount={drawingRecap.length}
              onViewDrawings={handleViewDrawingsFromGameEnd}
            />
          ) : roomView === "waiting" ? (
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
              players={players}
              myPlayerId={playerId}
              isHost={isHost}
              finalScores={finalScores}
              startBusy={startBusy}
              startError={startError}
              onStart={() => void handleStartGame()}
              drawingCount={drawingRecap.length}
              onViewDrawings={() => setRecapOpen(true)}
            />
          ) : (
            <main className="canvas-area">
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
                revealedWord={
                  phase === "round_end" ? lastRoundResult?.word ?? null : guessedWord
                }
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
                overlay={
                  phase === "choosing_word" && !amDrawer ? (
                    <ChoosingWordOverlay
                      drawerNickname={drawer?.nickname || "The next player"}
                      drawerNameColor={drawer?.nameColor}
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
                  showScores={scoringMode === "default"}
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
          )
        }
        chat={
          <RoomChatPanel
            messages={messages}
            players={players}
            mode={roomView}
            isDrawer={amDrawer}
            canGuess={canGuess}
            myPlayerId={playerId}
            targetWordLengths={splitMaskedWord(maskedWord).counts}
            hideMaskedPrompt={hideMaskedPrompt}
            onFocusChange={setIsInputFocused}
          />
        }
      />
    </div>
  );
}
