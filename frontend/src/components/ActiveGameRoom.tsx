import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { CanvasRef } from "../components/Canvas";
import { GameEndOverlay } from "../components/GameEndOverlay";
import { DrawingRecapGallery } from "../components/DrawingRecapGallery";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { AccountMenu } from "../components/AccountMenu";
import { RestartVoteBanner } from "../components/RestartVoteBanner";
import { RoomShell, type RoomShellMode } from "../components/RoomShell";
import {
  ConnectedRoomChatPanel,
  ConnectedRoomPlayersPanel,
  ConnectedWaitingRoomPanel,
  GameplayRegion,
} from "../components/GameRoomRegions";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { useVisualViewportCssVars } from "../hooks/useVisualViewportCssVars";
import { emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import { SettingsIcon } from "../components/SettingsIcon";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { recordRender } from "../lib/renderDiagnostics";
import type { AckResponse } from "../types";

export function ActiveGameRoom({ code }: { code: string }) {
  recordRender("activeGameRoom");
  const navigate = useNavigate();
  const { notify } = useToast();
  const openSettings = useSettingsStore((s) => s.openSettings);

  const canvasRef = useRef<CanvasRef | null>(null);
  const exitingRoomRef = useRef(false);
  const playersDrawerRef = useRef<HTMLElement | null>(null);
  const playersDrawerCloseRef = useRef<HTMLButtonElement | null>(null);
  const playersDrawerTitleId = useId();

  const playerId = useGameStore((s) => s.playerId);
  const clearSession = useGameStore((s) => s.clearSession);
  const setExitingRoom = useGameStore((s) => s.setExitingRoom);
  const reset = useGameStore((s) => s.reset);

  const roomState = useGameStore((s) => s.roomState);
  const phase = useGameStore((s) => s.phase);
  const drawerId = useGameStore((s) => s.drawerId);
  const scoringMode = useGameStore((s) => s.scoringMode);
  const finalScores = useGameStore((s) => s.finalScores);
  const drawingRecap = useGameStore((s) => s.drawingRecap);
  const restartVote = useGameStore((s) => s.restartVote);
  const restartVoteCooldownUntil = useGameStore((s) => s.restartVoteCooldownUntil);
  const dismissGameEnd = useGameStore((s) => s.dismissGameEnd);
  const isConnected = useGameStore((s) =>
    s.players.find((player) => player.playerId === s.playerId)?.connected ?? false,
  );
  const isAfk = useGameStore((s) =>
    s.players.find((player) => player.playerId === s.playerId)?.isAfk ?? false,
  );
  const isSpectator = useGameStore((s) =>
    s.players.find((player) => player.playerId === s.playerId)?.isSpectator ?? false,
  );

  const normalizedCode = code.trim().toUpperCase();
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [leaveConfirmationOpen, setLeaveConfirmationOpen] = useState(false);
  const [startBusy, setStartBusy] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [recapOpen, setRecapOpen] = useState(false);
  const [playersDrawerOpen, setPlayersDrawerOpen] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [restartClock, setRestartClock] = useState(() => Date.now());
  const isMobile = useMediaQuery("(max-width: 900px)");

  useVisualViewportCssVars();

  useFocusTrap(playersDrawerRef, {
    active: playersDrawerOpen,
    onEscape: () => setPlayersDrawerOpen(false),
    initialFocusRef: playersDrawerCloseRef,
  });

  useEffect(() => {
    if (restartVoteCooldownUntil <= Date.now()) return;
    const interval = window.setInterval(() => {
      const now = Date.now();
      setRestartClock(now);
      if (now >= restartVoteCooldownUntil) window.clearInterval(interval);
    }, 250);
    return () => window.clearInterval(interval);
  }, [restartVoteCooldownUntil]);

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
      setExitingRoom(true);
      clearSession();
      reset();
      navigate("/", { state: { criticalError: data?.reason || "You were kicked from the room." } });
    }
    function onVotedAfk(data: { message?: string }) {
      notify(data?.message || "You were marked AFK by room vote.", "warning");
    }
    // One seat per account per room: another tab took this one over. Say so
    // rather than leaving this tab on a board that has silently stopped.
    function onSuperseded(data: { reason?: string }) {
      exitingRoomRef.current = true;
      setExitingRoom(true);
      clearSession();
      reset();
      navigate("/", {
        state: {
          criticalError:
            data?.reason || "This room was opened in another tab.",
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

  async function handleProposeRestart() {
    if (restartBusy) return;
    setRestartBusy(true);
    try {
      const response = await emitWithAck<AckResponse>("propose_restart_vote", {});
      if (!response.ok) {
        notify(response.error || "Could not start a restart vote.", "error");
      }
    } catch (restartError) {
      notify(socketRequestErrorMessage(restartError, "start a restart vote"), "error");
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
        notify(response.error || "Could not record your restart vote.", "error");
      }
    } catch (restartError) {
      notify(socketRequestErrorMessage(restartError, "record your restart vote"), "error");
    } finally {
      setRestartBusy(false);
    }
  }

  function handleViewDrawingsFromGameEnd() {
    dismissGameEnd();
    setRecapOpen(true);
  }

  const amDrawer =
    (phase === "drawing" || phase === "choosing_word") && drawerId === playerId;
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
          {roomView === "playing" && canProposeRestart && !restartVote && (
            <button
              type="button"
              className="game-header-restart-button"
              disabled={restartBusy || restartCooldownSeconds > 0}
              onClick={() => void handleProposeRestart()}
              aria-label={restartCooldownSeconds > 0
                ? `Restart vote available in ${restartCooldownSeconds} seconds`
                : "Propose restarting the game"}
              title={restartCooldownSeconds > 0
                ? `Restart vote available in ${restartCooldownSeconds}s`
                : "Propose a vote to restart the game"}
            >
              <span className="header-action-icon" aria-hidden="true">↻</span>
              <span className="header-action-label">
                {restartCooldownSeconds > 0 ? `Restart · ${restartCooldownSeconds}s` : "Restart"}
              </span>
            </button>
          )}
          <AccountMenu />
          <button
            type="button"
            className="game-header-afk-button"
            style={{ background: isAfk ? "#f59e0b" : undefined, color: isAfk ? "#fff" : undefined }}
            onClick={handleToggleAfk}
            aria-label={isAfk ? "Back from AFK" : "Go AFK"}
            title={isAfk ? "Back from AFK" : "Go AFK"}
          >
            <span className="header-action-icon" aria-hidden="true">{isAfk ? "💤" : "AFK"}</span>
            <span className="header-action-label">{isAfk ? "AFK 💤" : "AFK"}</span>
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

      {roomView === "playing" && restartVote && (
        <RestartVoteBanner
          vote={restartVote}
          player={me}
          busy={restartBusy}
          onVote={(vote) => void handleRestartVote(vote)}
        />
      )}

      {playersDrawerOpen && (
        <div
          className="players-drawer-overlay"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPlayersDrawerOpen(false);
          }}
        >
          <aside
            ref={playersDrawerRef}
            className="players-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby={playersDrawerTitleId}
            tabIndex={-1}
            data-testid="players-drawer"
          >
            <div className="players-drawer-header">
              <h2 id={playersDrawerTitleId}>Players</h2>
              <button
                ref={playersDrawerCloseRef}
                type="button"
                className="players-drawer-close"
                onClick={() => setPlayersDrawerOpen(false)}
                aria-label="Close players"
              >
                ✕
              </button>
            </div>
            <div className="players-drawer-body sidebar-box">
              <ConnectedRoomPlayersPanel mode={roomView} />
            </div>
          </aside>
        </div>
      )}

      <RoomShell
        mode={roomView}
        players={
          <ConnectedRoomPlayersPanel mode={roomView} />
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
            <ConnectedWaitingRoomPanel
              finalScores={finalScores}
              startBusy={startBusy}
              startError={startError}
              onStart={() => void handleStartGame()}
              drawingCount={drawingRecap.length}
              onViewDrawings={() => setRecapOpen(true)}
            />
          ) : (
            <GameplayRegion canvasRef={canvasRef} />
          )
        }
        chat={
          <ConnectedRoomChatPanel mode={roomView} onFocusChange={setIsInputFocused} />
        }
      />
    </div>
  );
}
