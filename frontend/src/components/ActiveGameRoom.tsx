import { useCallback, useEffect, useRef, useState } from "react";
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
import { ConnectedPinControl } from "../components/ConnectedPinControl";
import { GameHeaderStatus } from "../components/GameHeaderStatus";
import { RoomNoticeChips } from "../components/RoomNoticeChips";
import { RoomVisibilityIcon } from "../components/RoomVisibilityIcon";
import { RoomDrainCue, RoomEndedCard, RoomPausedCard } from "../components/RoomStageNotice";
import { useRoomStage } from "../hooks/useServerNotices";
import { RoomMenuDropdown, RoomMenuSheet, type RoomMenuActions } from "../components/RoomMenu";
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
import {
  exitRoomHistory,
  RoomHistoryProvider,
  useBackCloses,
  useRoomHistory,
} from "../hooks/useRoomHistory";
import { useVisualViewportCssVars } from "../hooks/useVisualViewportCssVars";
import { emitTransient, emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import { isSigningOut } from "../store/authStore";
import { useToast } from "../lib/toast";
import {
  DotsIcon,
  MoonIcon,
  Wordmark,
} from "../components/icons";
import { selectAmDrawer, selectMe, useGameStore } from "../store/gameStore";
import { recordRender } from "../lib/renderDiagnostics";
import { CrashProbe } from "../lib/crashTestSeam";
import type { AckResponse } from "../types";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import { isKick, kickedText, supersededText } from "../lib/roomNotices.ts";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export function ActiveGameRoom({ code }: { code: string }) {
  recordRender("activeGameRoom");
  const navigate = useNavigate();
  const { notify } = useToast();

  const canvasRef = useRef<CanvasRef | null>(null);
  const exitingRoomRef = useRef(false);

  const playerId = useGameStore((s) => s.playerId);
  const clearSession = useGameStore((s) => s.clearSession);
  const setExitingRoom = useGameStore((s) => s.setExitingRoom);
  const reset = useGameStore((s) => s.reset);
  // Paused while the connection is down; ended once the server says the room is gone (#823).
  const stage = useRoomStage();

  const roomState = useGameStore((s) => s.roomState);
  const roomName = useGameStore((s) => s.name);
  // The room's own name, which is what somebody with a room and the Gallery
  // open side by side is looking for; the code until the name has arrived.
  useDocumentTitle(roomName || code);
  const roomIsPublic = useGameStore((s) => s.isPublic);
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
  const isMobile = useMediaQuery("(max-width: 900px)");
  // The identity chip gives up its name before anything else in the bar does
  // (after the room's), and is the avatar alone from here down - the compact
  // chip, drawn round, not the full one with its label hidden inside it.
  const identityCompact = useMediaQuery("(max-width: 1000px)");
  // Which seats belong to friends, asked once for the whole room. Here rather
  // than in the sidebar roster that first used it: that panel is not mounted
  // on a narrow layout, where the waiting roster and the guess pips draw the
  // same players and want the same marks (R-FRIEND-13). This component is the
  // one thing mounted for as long as the room is.
  useRoomFriendSeats();

  useVisualViewportCssVars();

  // Stable, so the memoised regions below are not re-rendered by a new
  // function on every room render (#987).
  const openPlayersSheet = useCallback(() => setPlayersSheetOpen(true), []);

  async function handleCopyLink() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(window.location.href);
      notify(ui.activeGameRoom.inviteLinkCopied, "success", 2500);
    } catch {
      notify(ui.activeGameRoom.couldNotCopyLink, "error");
    }
  }

  useEffect(() => {
    // Whose history entries to take off: read before the session is cleared,
    // which is what forgets the seat.
    const heldSeat = () => ({
      code: normalizedCode,
      seat: useGameStore.getState().playerId ?? "",
    });
    function onKicked(data: { code?: string }) {
      const who = heldSeat();
      exitingRoomRef.current = true;
      setExitingRoom(true);
      clearSession();
      reset();
      exitRoomHistory(who, (replace) => {
        navigate("/", {
          replace,
          state: { criticalError: kickedText(data?.code), kicked: isKick(data?.code) },
        });
      });
    }
    // One meaning, so nothing to read from the payload: its `message` is
    // English for a log.
    function onVotedAfk() {
      notify(ui.activeGameRoom.markedAfkByRoomVote, "warning");
    }
    // One seat per account per room: another tab took this one over. Say so
    // rather than leaving this tab on a board that has silently stopped.
    function onSuperseded(data: { code?: string }) {
      // This tab's own sign-out closes its socket the same way (#1007);
      // `logout` leaves the room itself, and a red "signed out" over a
      // chosen action is wrong.
      if (data?.code === "signed_out" && isSigningOut()) return;
      const who = heldSeat();
      exitingRoomRef.current = true;
      setExitingRoom(true);
      clearSession();
      reset();
      exitRoomHistory(who, (replace) => {
        navigate("/", {
          replace,
          state: {
            criticalError: supersededText(data?.code),
          },
        });
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
    const who = { code: normalizedCode, seat: playerId ?? "" };
    exitingRoomRef.current = true;
    setExitingRoom(true);
    clearSession();
    emitTransient("leave_room");
    reset();
    // The room's history entries go with it, and the lobby takes the place of
    // the entry the room was entered on: Back from the lobby then goes to
    // wherever that was, not to a room this player has left.
    exitRoomHistory(who, (replace) => navigate("/", { replace }));
  }

  function handleLeave() {
    if (roomState === "playing") {
      setLeaveConfirmationOpen(true);
      return;
    }
    performLeave();
  }

  // Back from the room is the Leave the room offers at that moment: the
  // Room menu's, which asks during a game, or the ended card's, which does not.
  function handleBackOnRoom() {
    if (stage.kind === "ended") performLeave();
    else handleLeave();
  }
  // Back is the room's own: a sheet on top closes, and Back on the room
  // itself is Leave, which gives up the seat rather than walking away from it
  // (R-UX-15).
  const roomHistory = useRoomHistory(normalizedCode, playerId ?? "", handleBackOnRoom);

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

  const roomMenuActions: RoomMenuActions = {
    code,
    isPlaying: roomView === "playing",
    isAfk,
    canProposeRestart: canProposeRestart && !restartVote,
    restartBusy,
    restartCooldownUntil: restartVoteCooldownUntil,
    onCopyLink: () => void handleCopyLink(),
    onOpenPlayers: isMobile ? openPlayersSheet : undefined,
    onToggleAfk: handleToggleAfk,
    onSaveImage: () => canvasRef.current?.saveImage(),
    onProposeRestart: () => void handleProposeRestart(),
    onLeave: handleLeave,
  };

  // Both post-game panels are about the *last* game, so a game starting
  // underneath one has to close it - otherwise the player reads last game's
  // screen over live gameplay and misses the start. Keyed on the room going
  // back to playing rather than on the game's first `turn_starting`, so it
  // also covers a player who was disconnected while the rematch began and is
  // synced into it.
  // Nothing can legitimately open either panel while playing: the buttons live
  // on the game over screen and the waiting room, and both leave the room in
  // "waiting". Highlights matter most - the store drops the recap once the
  // room is playing, so the panel would sit there telling the player the game
  // underway was too short to say anything about.
  if (roomState === "playing" && (recapOpen || highlightsOpen)) {
    setRecapOpen(false);
    setHighlightsOpen(false);
  }

  // The two post-game panels take the stage rather than sitting over it, but
  // they are opened and closed like sheets, so Back closes them like sheets.
  const recapShown = recapOpen && drawingRecap.length > 0;
  function closeRecap() {
    setRecapOpen(false);
    setRecapIndex(0);
  }
  useBackCloses(recapShown, closeRecap);
  useBackCloses(highlightsOpen && !recapShown, () => setHighlightsOpen(false));

  const room = (
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
      {/* One bar, three slots (#580): where you are, what is going on, you.
          The same component on both layouts, so a phone and a desktop can
          only differ in what they leave out: the room name and the wordmark
          are accessory and give way first, the clock, the round, the notice
          chips and the Room menu never do. The room code and every action
          that used to be an icon here are rows of the Room menu. */}
      <header
        className={`game-header${isMobile ? " game-header-mobile" : ""}`}
        data-testid="room-header"
        data-room-code={code}
        data-room-name={roomName || undefined}
      >
        <div className="game-header-start">
          {/* The way back to the lobby, which from a room is leaving it -
              so it asks first during a game, as Leave does. On every width:
              it is what says which game this is. */}
          <button
            type="button"
            className="game-header-home"
            onClick={handleLeave}
            title={ui.activeGameRoom.leaveRoom}
            aria-label={ui.activeGameRoom.leaveRoom}
          >
            <Wordmark size={isMobile ? 22 : 24} decorative />
          </button>
          {/* Public or private beside the name, and gone with it when the bar
              gives the name up: the waiting room's heading says it there. */}
          {!isMobile && roomName && (
            <span className="game-header-room-name">
              <span className="game-header-room-name-text">{roomName}</span>
              <RoomVisibilityIcon isPublic={roomIsPublic} />
            </span>
          )}
        </div>
        <div className="game-header-center">
          <GameHeaderStatus />
          <RoomNoticeChips compact={isMobile} />
          {/* Going AFK is a menu row; being away is worth seeing, because it
              skips your turns without asking. One click here comes back. */}
          {isAfk && (
            <button
              type="button"
              className="game-header-away"
              onClick={handleToggleAfk}
              aria-label={ui.activeGameRoom.backFromAfk}
              title={ui.activeGameRoom.backFromAfk}
            >
              <MoonIcon size={13} />
              <span>{ui.roomMenuSheet.afk}</span>
            </button>
          )}
        </div>
        <div className="game-header-actions">
          {isMobile ? (
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
          ) : (
            <RoomMenuDropdown actions={roomMenuActions} />
          )}
          <AccountMenu inRoom compact={identityCompact} />
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
        <RoomMenuSheet actions={roomMenuActions} onDismiss={() => setRoomMenuOpen(false)} />
      )}

      {/* Nothing in a production build; the E2E suite's way to crash the room. */}
      <CrashProbe scope="room" />
      {stage.kind === "ended" ? (
        <RoomEndedCard reason={stage.reason} onLeave={performLeave} />
      ) : (
        <RoomShell
          inert={stage.kind === "paused"}
          overlay={
            stage.kind === "paused" ? (
              <RoomPausedCard
                cause={stage.cause}
                onReload={() => window.location.reload()}
                onLeave={performLeave}
              />
            ) : (
              <RoomDrainCue playing={roomView === "playing"} />
            )
          }
          mode={roomView}
          players={
            <ConnectedRoomPlayersPanel mode={roomView} />
          }
          main={
            recapShown ? (
              <DrawingRecapGallery
                entries={drawingRecap}
                initialIndex={recapIndex}
                onClose={closeRecap}
                loadEntry={loadRecapDrawing}
                renderReactions={(entry) => (
                  <ConnectedDrawingReactionControl
                    turnId={entry.turnId}
                    drawerId={entry.drawerId}
                    placement="panel"
                    visible={entry.available !== false}
                  />
                )}
                renderActions={(entry) => (
                  <ConnectedPinControl turnId={entry.turnId} visible={entry.available !== false} />
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
                onOpenPlayers={isMobile ? openPlayersSheet : undefined}
              />
            )
          }
          chat={
            <ConnectedRoomChatPanel mode={roomView} onFocusChange={setIsInputFocused} />
          }
        />
      )}
    </div>
  );
  // Every sheet in the room reaches the room's history through this, and
  // only the room provides it: a sheet anywhere else leaves Back alone.
  return <RoomHistoryProvider value={roomHistory}>{room}</RoomHistoryProvider>;
}
