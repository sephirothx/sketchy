import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { CanvasRef } from "../components/Canvas";
import { GameEndOverlay } from "../components/GameEndOverlay";
import { DrawingRecapGallery } from "../components/DrawingRecapGallery";
import { loadRecapDrawing } from "../lib/recapDrawings";
import { GameHighlightsPanel } from "../components/GameHighlightsPanel";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { AccountMenu } from "../components/AccountMenu";
import { AfkCheckDialog } from "../components/AfkCheckDialog";
import { RestartVoteBanner } from "../components/RestartVoteBanner";
import { ColorblindSafeSuggestionBanner } from "../components/ColorblindSafeSuggestionBanner";
import { RoomShell, type RoomShellMode } from "../components/RoomShell";
import { ConnectedDrawingReactionControl } from "../components/GameRoomRegions";
import { GameHeaderStatus } from "../components/GameHeaderStatus";
import { RoomMenuSheet } from "../components/RoomMenuSheet";
import { BottomSheet } from "../components/ui/BottomSheet";
import {
  ConnectedRoomChatPanel,
  ConnectedRoomPlayersPanel,
  ConnectedWaitingRoomPanel,
  GameplayRegion,
} from "../components/GameRoomRegions";
import { useAfkCheck } from "../hooks/useAfkCheck";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useRoomFriendSeats } from "../hooks/useRoomFriendSeats";
import { useOpenSettings } from "../hooks/useSettingsRoute";
import { useVisualViewportCssVars } from "../hooks/useVisualViewportCssVars";
import { emitTransient, emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import {
  CopyIcon,
  DotsIcon,
  Wordmark,
  DownloadIcon,
  GearIcon,
  LeaveIcon,
  MoonIcon,
  RoundsIcon,
} from "../components/icons";
import { selectAmDrawer, selectMe, useGameStore } from "../store/gameStore";
import { recordRender } from "../lib/renderDiagnostics";
import { CrashProbe } from "../lib/crashTestSeam";
import type { AckResponse } from "../types";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import { kickedText, supersededText } from "../lib/roomNotices.ts";

export function ActiveGameRoom({ code }: { code: string }) {
  recordRender("activeGameRoom");
  const navigate = useNavigate();
  const { notify } = useToast();
  const openSettings = useOpenSettings();

  const canvasRef = useRef<CanvasRef | null>(null);
  const exitingRoomRef = useRef(false);

  const playerId = useGameStore((s) => s.playerId);
  const clearSession = useGameStore((s) => s.clearSession);
  const setExitingRoom = useGameStore((s) => s.setExitingRoom);
  const reset = useGameStore((s) => s.reset);

  const roomState = useGameStore((s) => s.roomState);
  const roomName = useGameStore((s) => s.name);
  const phase = useGameStore((s) => s.phase);
  const scoringMode = useGameStore((s) => s.scoringMode);
  const finalScores = useGameStore((s) => s.finalScores);
  const drawingRecap = useGameStore((s) => s.drawingRecap);
  const gameHighlights = useGameStore((s) => s.gameHighlights);
  const restartVote = useGameStore((s) => s.restartVote);
  const restartVoteCooldownUntil = useGameStore((s) => s.restartVoteCooldownUntil);
  const colorblindSafeSuggestion = useGameStore((s) => s.colorblindSafeSuggestion);
  const dismissGameEnd = useGameStore((s) => s.dismissGameEnd);
  // One roster scan, not one per field.
  const isConnected = useGameStore((s) => selectMe(s)?.connected ?? false);
  const isAfk = useGameStore((s) => selectMe(s)?.isAfk ?? false);
  // Armed for the whole time a seat is held, waiting room included: an absent
  // host holding a room nobody can start is half of what the check is for.
  // Not while already AFK - the flag is the answer the check was after.
  const afkCheck = useAfkCheck(!isAfk);
  const isSpectator = useGameStore((s) => selectMe(s)?.isSpectator ?? false);
  const isHost = useGameStore((s) => selectMe(s)?.isHost ?? false);

  const normalizedCode = code.trim().toUpperCase();
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [leaveConfirmationOpen, setLeaveConfirmationOpen] = useState(false);
  const [startBusy, setStartBusy] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [recapOpen, setRecapOpen] = useState(false);
  const [recapIndex, setRecapIndex] = useState(0);
  const [highlightsOpen, setHighlightsOpen] = useState(false);
  const [playersSheetOpen, setPlayersSheetOpen] = useState(false);
  const [roomMenuOpen, setRoomMenuOpen] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [colorSuggestionBusy, setColorSuggestionBusy] = useState(false);
  const [restartClock, setRestartClock] = useState(() => Date.now());
  const isMobile = useMediaQuery("(max-width: 900px)");
  // Which seats belong to friends, asked once for the whole room. Here rather
  // than in the sidebar roster that first used it: that panel is not mounted
  // on a narrow layout, where the waiting roster and the guess pips draw the
  // same players and want the same marks (R-FRIEND-13). This component is the
  // one thing mounted for as long as the room is.
  useRoomFriendSeats();

  useVisualViewportCssVars();

  useEffect(() => {
    if (restartVoteCooldownUntil <= Date.now()) return;
    const interval = window.setInterval(() => {
      const now = Date.now();
      setRestartClock(now);
      if (now >= restartVoteCooldownUntil) window.clearInterval(interval);
    }, 250);
    return () => window.clearInterval(interval);
  }, [restartVoteCooldownUntil]);

  async function handleCopyLink() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(window.location.href);
      notify(ui.activeGameRoom.inviteLinkCopied, "success", 2500);
    } catch {
      notify(ui.activeGameRoom.couldnTCopyLinkCopyFrom, "error");
    }
  }

  useEffect(() => {
    function onKicked(data: { code?: string }) {
      exitingRoomRef.current = true;
      setExitingRoom(true);
      clearSession();
      reset();
      navigate("/", { state: { criticalError: kickedText(data?.code) } });
    }
    // One meaning, so nothing to read from the payload: its `message` is
    // English for a log.
    function onVotedAfk() {
      notify(ui.activeGameRoom.markedAfkByRoomVote, "warning");
    }
    // One seat per account per room: another tab took this one over. Say so
    // rather than leaving this tab on a board that has silently stopped.
    function onSuperseded(data: { code?: string }) {
      exitingRoomRef.current = true;
      setExitingRoom(true);
      clearSession();
      reset();
      navigate("/", {
        state: {
          criticalError: supersededText(data?.code),
        },
      });
    }
    socket.on("kicked", onKicked);
    socket.on("voted_afk", onVotedAfk);
    socket.on("session_superseded", onSuperseded);
    return () => {
      socket.off("kicked", onKicked);
      socket.off("voted_afk", onVotedAfk);
      socket.off("session_superseded", onSuperseded);
    };
  }, [clearSession, navigate, normalizedCode, notify, reset, setExitingRoom]);

  function performLeave() {
    exitingRoomRef.current = true;
    setExitingRoom(true);
    clearSession();
    emitTransient("leave_room");
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
    emitTransient("toggle_afk");
  }

  async function handleStartGame() {
    setStartBusy(true);
    setStartError(null);
    try {
      const response = await emitWithAck<AckResponse>("start_game", {});
      if (!response.ok) setStartError(refusalText(response, ui.activeGameRoom.couldNotStartGamePleaseTry));
    } catch (startError) {
      setStartError(socketRequestErrorMessage(startError, ui.activeGameRoom.startTheGame));
    } finally {
      setStartBusy(false);
    }
  }

  async function handleProposeRestart() {
    if (restartBusy) return;
    setRestartBusy(true);
    try {
      const response = await emitWithAck<AckResponse>("propose_restart_vote", {});
      if (!response.ok) {
        notify(refusalText(response, ui.activeGameRoom.couldNotStartRestartVote), "error");
      }
    } catch (restartError) {
      notify(socketRequestErrorMessage(restartError, ui.activeGameRoom.startARestartVote), "error");
    } finally {
      setRestartBusy(false);
    }
  }

  async function handleRestartVote(vote: boolean) {
    if (restartBusy) return;
    setRestartBusy(true);
    try {
      const response = await emitWithAck<AckResponse>("cast_restart_vote", { vote });
      if (!response.ok) {
        notify(refusalText(response, ui.activeGameRoom.couldNotRecordYourRestartVote), "error");
      }
    } catch (restartError) {
      notify(socketRequestErrorMessage(restartError, ui.activeGameRoom.recordYourRestartVote), "error");
    } finally {
      setRestartBusy(false);
    }
  }

  async function handleColorSuggestion(action: "accept" | "dismiss") {
    if (colorSuggestionBusy) return;
    setColorSuggestionBusy(true);
    try {
      const response = await emitWithAck<AckResponse>(
        action === "accept"
          ? "accept_colorblind_suggestion"
          : "dismiss_colorblind_suggestion",
        {},
      );
      if (!response.ok) {
        notify(
          refusalText(
            response,
            action === "accept"
              ? ui.activeGameRoom.couldNotAcceptSuggestion
              : ui.activeGameRoom.couldNotDismissSuggestion,
          ),
          "error",
        );
      }
    } catch (suggestionError) {
      notify(
        socketRequestErrorMessage(
          suggestionError,
          action === "accept"
            ? ui.activeGameRoom.acceptTheColorSuggestion
            : ui.activeGameRoom.dismissTheColorSuggestion,
        ),
        "error",
      );
    } finally {
      setColorSuggestionBusy(false);
    }
  }

  function handleViewDrawingsFromGameEnd() {
    dismissGameEnd();
    setRecapOpen(true);
  }

  function handleViewHighlightsFromGameEnd() {
    dismissGameEnd();
    setHighlightsOpen(true);
  }

  const amDrawer = useGameStore(selectAmDrawer);
  const me = playerId
    ? { playerId, connected: isConnected, isAfk, isSpectator }
    : undefined;
  const restartCooldownSeconds = Math.max(
    0,
    Math.ceil((restartVoteCooldownUntil - restartClock) / 1000),
  );
  const canProposeRestart = Boolean(
    roomState === "playing"
    && isConnected
    && !isAfk
    && !isSpectator,
  );

  // Density mode only: hide chrome while guessing on mobile. Positioning stays on the stable vv-pinned shell.
  const isGuessFocused = isInputFocused && phase === "drawing" && isMobile;
  const roomView: RoomShellMode =
    phase === "game_end" && finalScores ? "game-end" : roomState;

  if (playersSheetOpen && (roomView !== "playing" || !isMobile)) {
    setPlayersSheetOpen(false);
  }
  if (roomMenuOpen && !isMobile) {
    setRoomMenuOpen(false);
  }

  // Both post-game panels are about the *last* game, so a game starting
  // underneath one has to close it - otherwise the player reads last game's
  // screen over live gameplay and misses the start. Keyed on the room going
  // back to playing rather than on `game_started`, so it also covers a player
  // who was disconnected while the rematch began and is synced into it.
  // Nothing can legitimately open either panel while playing: the buttons live
  // on the game over screen and the waiting room, and both leave the room in
  // "waiting". Highlights matter most - room state drops `lastGameHighlights`
  // once the room is playing, so the panel would sit there telling the player
  // the game underway was too short to say anything about.
  if (roomState === "playing" && (recapOpen || highlightsOpen)) {
    setRecapOpen(false);
    setHighlightsOpen(false);
  }

  return (
    <div
      className={`game-room${roomView === "playing" ? " game-room-playing" : ""}${isGuessFocused ? " guess-focused" : ""}`}
    >
      {afkCheck.secondsLeft !== null && (
        <AfkCheckDialog
          secondsLeft={afkCheck.secondsLeft}
          onAnswer={afkCheck.answer}
        />
      )}
      {leaveConfirmationOpen && (
        <ConfirmationDialog
          title={amDrawer ? ui.activeGameRoom.leaveDuringYourTurn : ui.activeGameRoom.leaveActiveGame}
          description={amDrawer
            ? ui.activeGameRoom.youReTheCurrentDrawer
            : ui.activeGameRoom.theGameIsStillIn}
          confirmLabel={ui.activeGameRoom.leaveGame}
          onCancel={() => setLeaveConfirmationOpen(false)}
          onConfirm={() => {
            setLeaveConfirmationOpen(false);
            performLeave();
          }}
        />
      )}
      {isMobile ? (
        /* Phone status band: what the room is, how long is left, and one way
           in to everything else. The eight-icon strip this replaces put a red
           Leave a thumb-width from Settings; those live in the ⋯ sheet now. */
        <header className="game-header game-header-mobile">
          {/* The mark earns its place even here: this is the only screen a
              player is on for ten minutes at a stretch, and it is what says
              which game they are in when they come back to the tab. */}
          <span className="game-header-mark" aria-hidden="true">
            <Wordmark size={22} />
          </span>
          <button
            type="button"
            className="room-copy-button"
            data-room-code={code}
            onClick={() => void handleCopyLink()}
            aria-label={ui.activeGameRoom.copyRoomInviteLink}
            title={ui.activeGameRoom.clickCopyRoomInviteLink}
          >
            <span>{code}</span>
            <CopyIcon size={13} />
          </button>
          <GameHeaderStatus />
          <button
            type="button"
            className="btn btn-icon game-header-menu-button"
            onClick={() => setRoomMenuOpen(true)}
            aria-label={ui.activeGameRoom.roomMenu}
            aria-haspopup="dialog"
            title={ui.activeGameRoom.roomMenu}
            data-testid="open-room-menu"
          >
            <DotsIcon size={18} />
          </button>
        </header>
      ) : (
        <header className="game-header">
          <div className="game-header-start">
            {roomName && <span className="game-header-room-name">{roomName}</span>}
            <button
              type="button"
              className="room-copy-button"
              data-room-code={code}
              onClick={() => void handleCopyLink()}
              title={ui.activeGameRoom.clickCopyRoomInviteLink}
            >
              <span>{code}</span>
              <CopyIcon size={13} />
            </button>
          </div>
          <GameHeaderStatus />
          <div className="game-header-actions">
            {roomView === "playing" && canProposeRestart && !restartVote && (
              <button
                type="button"
                className="btn btn-icon btn-compact game-header-restart-button"
                disabled={restartBusy || restartCooldownSeconds > 0}
                onClick={() => void handleProposeRestart()}
                aria-label={restartCooldownSeconds > 0
                  ? ui.activeGameRoom.restartVoteAvailableInRestartCooldownSeconds({ restartCooldownSeconds })
                  : ui.activeGameRoom.proposeRestartingTheGame}
                title={restartCooldownSeconds > 0
                  ? ui.activeGameRoom.restartVoteAvailableInRestartCooldownSeconds2({ restartCooldownSeconds })
                  : ui.activeGameRoom.proposeAVoteToRestart}
              >
                <RoundsIcon size={16} />
                {restartCooldownSeconds > 0 && (
                  <span className="game-header-restart-count" aria-hidden="true">
                    {restartCooldownSeconds}
                  </span>
                )}
              </button>
            )}
            <AccountMenu compact />
            <button
              type="button"
              className={`game-header-afk-button${isAfk ? " is-afk" : ""}`}
              aria-pressed={isAfk}
              onClick={handleToggleAfk}
              aria-label={isAfk ? ui.activeGameRoom.backFromAfk : ui.activeGameRoom.goAfk}
              title={isAfk ? ui.activeGameRoom.backFromAfk : ui.activeGameRoom.goAfk}
            >
              <MoonIcon size={14} />
              <span className="header-action-label">{ui.activeGameRoom.afk}</span>
            </button>
            {roomView === "playing" && (
              <button
                type="button"
                className="btn btn-icon btn-compact save-image-button game-header-save-button"
                onClick={() => canvasRef.current?.saveImage()}
                aria-label={ui.activeGameRoom.saveImage}
                title={ui.activeGameRoom.saveDrawnImageFile}
              >
                <DownloadIcon size={16} />
              </button>
            )}
            <button
              type="button"
              className="btn btn-icon btn-compact header-settings-button"
              onClick={() => openSettings()}
              title={ui.activeGameRoom.playerSettings}
              aria-label={ui.activeGameRoom.playerSettings}
            >
              <GearIcon size={16} />
            </button>
            <span className="game-header-divider" aria-hidden="true" />
            <button
              type="button"
              className="btn btn-danger-ghost btn-compact game-header-leave-button"
              onClick={handleLeave}
              aria-label={ui.activeGameRoom.leaveRoom}
              title={ui.activeGameRoom.leaveRoom}
            >
              <LeaveIcon size={14} />
              <span className="header-action-label">{ui.activeGameRoom.leave}</span>
            </button>
          </div>
        </header>
      )}

      {roomView === "playing" && restartVote && (
        <RestartVoteBanner
          vote={restartVote}
          player={me}
          busy={restartBusy}
          onVote={(vote) => void handleRestartVote(vote)}
        />
      )}

      {isHost && colorblindSafeSuggestion && (
        <ColorblindSafeSuggestionBanner
          busy={colorSuggestionBusy}
          onAccept={() => void handleColorSuggestion("accept")}
          onDismiss={() => void handleColorSuggestion("dismiss")}
        />
      )}

      {/* A sheet rather than the old full-height left drawer: the canvas stays
          visible above it, so checking the score no longer means covering the
          drawing you are trying to guess. */}
      {playersSheetOpen && (
        <BottomSheet
          title={ui.activeGameRoom.players}
          height="55%"
          className="players-sheet"
          testId="players-drawer"
          closeLabel={ui.activeGameRoom.closePlayers}
          onDismiss={() => setPlayersSheetOpen(false)}
        >
          <ConnectedRoomPlayersPanel mode={roomView} />
        </BottomSheet>
      )}

      {roomMenuOpen && (
        <RoomMenuSheet
          isPlaying={roomView === "playing"}
          isAfk={isAfk}
          canProposeRestart={canProposeRestart && !restartVote}
          restartBusy={restartBusy}
          restartCooldownSeconds={restartCooldownSeconds}
          onDismiss={() => setRoomMenuOpen(false)}
          onCopyLink={() => void handleCopyLink()}
          onOpenPlayers={() => setPlayersSheetOpen(true)}
          onToggleAfk={handleToggleAfk}
          onSaveImage={() => canvasRef.current?.saveImage()}
          onOpenSettings={() => openSettings()}
          onProposeRestart={() => void handleProposeRestart()}
          onLeave={handleLeave}
        />
      )}

      {/* Nothing in a production build; the E2E suite's way to crash the room. */}
      <CrashProbe scope="room" />
      <RoomShell
        mode={roomView}
        players={
          <ConnectedRoomPlayersPanel mode={roomView} />
        }
        main={
          recapOpen && drawingRecap.length > 0 ? (
            <DrawingRecapGallery
              entries={drawingRecap}
              initialIndex={recapIndex}
              onClose={() => {
                setRecapOpen(false);
                setRecapIndex(0);
              }}
              loadEntry={loadRecapDrawing}
              renderReactions={(entry) => (
                <ConnectedDrawingReactionControl
                  turnId={entry.turnId}
                  drawerId={entry.drawerId}
                  placement="panel"
                  visible={entry.available !== false}
                />
              )}
            />
          ) : highlightsOpen ? (
            <GameHighlightsPanel
              highlights={gameHighlights}
              onClose={() => setHighlightsOpen(false)}
              onOpenDrawing={(index) => {
                setHighlightsOpen(false);
                setRecapIndex(index);
                setRecapOpen(true);
              }}
            />
          ) : roomView === "game-end" && finalScores ? (
            <GameEndOverlay
              scores={finalScores}
              myPlayerId={playerId}
              scoringMode={scoringMode}
              onContinue={dismissGameEnd}
              drawingCount={drawingRecap.length}
              onViewDrawings={handleViewDrawingsFromGameEnd}
              highlightCount={gameHighlights.length}
              onViewHighlights={handleViewHighlightsFromGameEnd}
            />
          ) : roomView === "waiting" ? (
            <ConnectedWaitingRoomPanel
              finalScores={finalScores}
              startBusy={startBusy}
              startError={startError}
              onStart={() => void handleStartGame()}
              drawingCount={drawingRecap.length}
              onViewDrawings={() => setRecapOpen(true)}
              highlightCount={gameHighlights.length}
              onViewHighlights={() => setHighlightsOpen(true)}
            />
          ) : (
            <GameplayRegion
              canvasRef={canvasRef}
              onOpenPlayers={isMobile ? () => setPlayersSheetOpen(true) : undefined}
            />
          )
        }
        chat={
          <ConnectedRoomChatPanel mode={roomView} onFocusChange={setIsInputFocused} />
        }
      />
    </div>
  );
}
