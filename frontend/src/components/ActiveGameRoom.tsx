import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { CanvasRef } from "../components/Canvas";
import { GameEndOverlay } from "../components/GameEndOverlay";
import { DrawingRecapGallery } from "../components/DrawingRecapGallery";
import { loadRecapDrawing } from "../lib/recapDrawings";
import { GameHighlightsPanel } from "../components/GameHighlightsPanel";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { AccountMenu } from "../components/AccountMenu";
import { RestartVoteBanner } from "../components/RestartVoteBanner";
import { ColorblindSafeSuggestionBanner } from "../components/ColorblindSafeSuggestionBanner";
import { RoomShell, type RoomShellMode } from "../components/RoomShell";
import { GameHeaderStatus } from "../components/GameHeaderStatus";
import {
  ConnectedRoomChatPanel,
  ConnectedRoomPlayersPanel,
  ConnectedWaitingRoomPanel,
  GameplayRegion,
} from "../components/GameRoomRegions";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { useVisualViewportCssVars } from "../hooks/useVisualViewportCssVars";
import { emitTransient, emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import {
  CopyIcon,
  DownloadIcon,
  GearIcon,
  LeaveIcon,
  MoonIcon,
  RoundsIcon,
  UsersIcon,
  XIcon,
} from "../components/icons";
import { selectAmDrawer, selectMe, useGameStore } from "../store/gameStore";
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
  const isSpectator = useGameStore((s) => selectMe(s)?.isSpectator ?? false);
  const isHost = useGameStore((s) => selectMe(s)?.isHost ?? false);

  const normalizedCode = code.trim().toUpperCase();
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [leaveConfirmationOpen, setLeaveConfirmationOpen] = useState(false);
  const [startBusy, setStartBusy] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [recapOpen, setRecapOpen] = useState(false);
  const [highlightsOpen, setHighlightsOpen] = useState(false);
  const [playersDrawerOpen, setPlayersDrawerOpen] = useState(false);
  const [restartBusy, setRestartBusy] = useState(false);
  const [colorSuggestionBusy, setColorSuggestionBusy] = useState(false);
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
          response.error || `Could not ${action} the color suggestion.`,
          "error",
        );
      }
    } catch (suggestionError) {
      notify(
        socketRequestErrorMessage(suggestionError, `${action} the color suggestion`),
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

  if (playersDrawerOpen && (roomView !== "playing" || !isMobile)) {
    setPlayersDrawerOpen(false);
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
          {roomName && <span className="game-header-room-name">{roomName}</span>}
          <button
            type="button"
            className="room-copy-button"
            data-room-code={code}
            onClick={() => void handleCopyLink()}
            title="Click to copy room invite link"
          >
            <span>{code}</span>
            <CopyIcon size={13} />
          </button>
          {roomView === "playing" && isMobile && (
            <button
              type="button"
              className="btn btn-icon btn-compact game-header-players-button"
              onClick={() => setPlayersDrawerOpen(true)}
              aria-label="View players"
              title="View players"
              data-testid="open-players-drawer"
            >
              <UsersIcon size={16} />
            </button>
          )}
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
                ? `Restart vote available in ${restartCooldownSeconds} seconds`
                : "Propose restarting the game"}
              title={restartCooldownSeconds > 0
                ? `Restart vote available in ${restartCooldownSeconds}s`
                : "Propose a vote to restart the game"}
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
            aria-label={isAfk ? "Back from AFK" : "Go AFK"}
            title={isAfk ? "Back from AFK" : "Go AFK"}
          >
            <MoonIcon size={14} />
            <span className="header-action-label">AFK</span>
          </button>
          {roomView === "playing" && (
            <button
              type="button"
              className="btn btn-icon btn-compact save-image-button game-header-save-button"
              onClick={() => canvasRef.current?.saveImage()}
              aria-label="Save image"
              title="Save drawn image to file"
            >
              <DownloadIcon size={16} />
            </button>
          )}
          <button
            type="button"
            className="btn btn-icon btn-compact header-settings-button"
            onClick={openSettings}
            title="Player settings"
            aria-label="Player settings"
          >
            <GearIcon size={16} />
          </button>
          <span className="game-header-divider" aria-hidden="true" />
          <button
            type="button"
            className="btn btn-danger-ghost btn-compact game-header-leave-button"
            onClick={handleLeave}
            aria-label="Leave room"
            title="Leave room"
          >
            <LeaveIcon size={14} />
            <span className="header-action-label">Leave</span>
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

      {isHost && colorblindSafeSuggestion && (
        <ColorblindSafeSuggestionBanner
          busy={colorSuggestionBusy}
          onAccept={() => void handleColorSuggestion("accept")}
          onDismiss={() => void handleColorSuggestion("dismiss")}
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
                <XIcon size={16} />
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
              loadEntry={loadRecapDrawing}
            />
          ) : highlightsOpen ? (
            <GameHighlightsPanel
              highlights={gameHighlights}
              onClose={() => setHighlightsOpen(false)}
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
