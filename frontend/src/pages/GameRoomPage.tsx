import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
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
import { useVisualViewportCssVars } from "../hooks/useVisualViewportCssVars";
import { emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import { splitMaskedWord } from "../lib/maskedWord";
import { SettingsIcon } from "../components/SettingsIcon";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, DrawTool, RoomPreviewResponse, RoomSummary } from "../types";

type EntryStatus = "loading" | "preview";

const INVITE_LOADING_DELAY_MS = 250;

function hintModeLabel(room: RoomSummary) {
  if (room.hideMaskedPrompt) return "Prompt details hidden";
  if (room.hintMode === "checkpoints") return "Timed letter hints";
  if (room.hintMode === "purchase") return "Buyable letter hints";
  if (room.hintMode === "wheel") return "Wheel-style letter hints";
  return "No letter hints";
}

function DelayedInviteLoader() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timeout = window.setTimeout(() => setVisible(true), INVITE_LOADING_DELAY_MS);
    return () => window.clearTimeout(timeout);
  }, []);

  if (!visible) return null;

  return (
    <main className="invite-card invite-loading-card" aria-live="polite">
      <div className="invite-loading-spinner" aria-hidden="true" />
      <h1>Checking your invite…</h1>
      <p>Loading room details.</p>
    </main>
  );
}

export function GameRoomPage() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const { notify } = useToast();
  const openSettings = useSettingsStore((s) => s.openSettings);
  const nameColor = useSettingsStore((s) => s.nameColor);

  const canvasRef = useRef<CanvasRef | null>(null);
  const exitingRoomRef = useRef(false);

  const nickname = useGameStore((s) => s.nickname);
  const setNickname = useGameStore((s) => s.setNickname);
  const playerId = useGameStore((s) => s.playerId);
  const activeRoomId = useGameStore((s) => s.roomId);
  const activeRoomCode = useGameStore((s) => s.code);
  const setSession = useGameStore((s) => s.setSession);
  const getStoredReconnectSecret = useGameStore((s) => s.getStoredReconnectSecret);
  const clearStoredReconnectSecret = useGameStore((s) => s.clearStoredReconnectSecret);
  const reset = useGameStore((s) => s.reset);

  const roomState = useGameStore((s) => s.roomState);
  const players = useGameStore((s) => s.players);
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

  const normalizedCode = code?.trim().toUpperCase() ?? "";
  const hasActiveSession = Boolean(
    playerId
      && activeRoomId
      && activeRoomCode?.toUpperCase() === normalizedCode,
  );

  const [joinError, setJoinError] = useState<string | null>(null);
  const [entryStatus, setEntryStatus] = useState<EntryStatus>("loading");
  const [roomPreview, setRoomPreview] = useState<RoomSummary | null>(null);
  const [nicknameInput, setNicknameInput] = useState(nickname);
  const [entryError, setEntryError] = useState<string | null>(null);
  const [entryNotice, setEntryNotice] = useState<string | null>(null);
  const [entryBusy, setEntryBusy] = useState(false);
  const [color, setColor] = useState("#000000");
  const [brushWidth, setBrushWidth] = useState(6);
  const [eraserWidth, setEraserWidth] = useState(24);
  const [tool, setTool] = useState<DrawTool>("pen");
  const [wasDrawer, setWasDrawer] = useState(false);
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
    if (!normalizedCode) return;
    if (hasActiveSession) return;
    if (exitingRoomRef.current) return;

    let cancelled = false;

    async function loadEntry() {
      try {
        const storedReconnectSecret = getStoredReconnectSecret(normalizedCode);
        if (storedReconnectSecret) {
          const reconnect = await emitWithAck<AckResponse>("join_room", {
            code: normalizedCode,
            nickname,
            nameColor,
            reconnectSecret: storedReconnectSecret,
          });
          if (cancelled) return;
          if (reconnect.ok && reconnect.roomId && reconnect.code && reconnect.playerId && reconnect.reconnectSecret) {
            setSession({
              roomId: reconnect.roomId,
              code: reconnect.code,
              playerId: reconnect.playerId,
              reconnectSecret: reconnect.reconnectSecret,
            });
            return;
          }
          if (!reconnect.invalidReconnectSecret) {
            setJoinError(reconnect.error || "Could not reconnect to this room");
            return;
          }
          clearStoredReconnectSecret(normalizedCode);
          setEntryNotice("Your previous session expired. Choose how you would like to rejoin.");
        }

        const preview = await emitWithAck<RoomPreviewResponse>("get_room_preview", {
          code: normalizedCode,
        });
        if (cancelled) return;
        if (preview.ok && preview.room) {
          setRoomPreview(preview.room);
          setEntryStatus("preview");
        } else {
          setJoinError(preview.error || "This room is no longer available");
        }
      } catch (loadError) {
        if (!cancelled) setJoinError(socketRequestErrorMessage(loadError, "load this room"));
      }
    }
    loadEntry();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [normalizedCode, hasActiveSession]);

  async function handleEntryJoin(asSpectator: boolean) {
    const trimmedNickname = nicknameInput.trim();
    if (!trimmedNickname) {
      setEntryError("Enter a nickname to continue.");
      return;
    }
    if (!code) return;

    setEntryBusy(true);
    setEntryError(null);
    try {
      const response = await emitWithAck<AckResponse>("join_room", {
        code: code.trim().toUpperCase(),
        nickname: trimmedNickname,
        nameColor,
        asSpectator,
      });

      if (response.ok && response.roomId && response.code && response.playerId && response.reconnectSecret) {
        setNickname(trimmedNickname);
        setSession({ roomId: response.roomId, code: response.code, playerId: response.playerId, reconnectSecret: response.reconnectSecret });
        return;
      }
      if (!asSpectator && response.error === "Room is full") {
        setRoomPreview((current) => current ? { ...current, isFull: true } : current);
        setEntryError("The player slots just filled up, but you can still spectate.");
        return;
      }
      setEntryError(response.error || "Could not join this room");
    } catch (joinRequestError) {
      setEntryError(socketRequestErrorMessage(joinRequestError, asSpectator ? "join as a spectator" : "join this room"));
    } finally {
      setEntryBusy(false);
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

  const activeWidth = tool === "eraser" ? eraserWidth : brushWidth;

  function handleWidthChange(newWidth: number) {
    if (tool === "eraser") {
      setEraserWidth(newWidth);
    } else {
      setBrushWidth(newWidth);
    }
  }

  // Reset to the default color and tool whenever a new drawing turn starts
  // for this player, instead of carrying over whatever color/tool was last
  // picked. Done during render (rather than an effect) per React's
  // "adjusting state when a prop changes" pattern, to avoid an extra render
  // pass.
  if (amDrawer !== wasDrawer) {
    setWasDrawer(amDrawer);
    if (amDrawer) {
      setColor("#000000");
      setTool("pen");
      setBrushWidth(6);
      setEraserWidth(24);
    }
  }

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

  if (!hasActiveSession) {
    return (
      <div className="invite-entry-page">
        <header className="invite-entry-header">
          <button type="button" className="invite-brand" onClick={() => navigate("/")}>
            Sketchy
          </button>
          <button
            type="button"
            className="header-settings-button"
            onClick={openSettings}
            title="Game Settings"
          >
            <SettingsIcon size={16} />
            <span>Settings</span>
          </button>
        </header>

        {joinError ? (
          <main className="invite-card invite-unavailable-card">
            <div className="invite-status-icon" aria-hidden="true">✕</div>
            <p className="invite-eyebrow">Room {code?.toUpperCase()}</p>
            <h1>Room unavailable</h1>
            <p>{joinError}</p>
            <button type="button" className="invite-primary-button" onClick={() => navigate("/")}>
              Back to lobby
            </button>
          </main>
        ) : entryStatus === "loading" || !roomPreview ? (
          <DelayedInviteLoader />
        ) : (
          <main className="invite-card">
            <div className="invite-card-heading">
              <div>
                <p className="invite-eyebrow">
                  {roomPreview.isPublic ? "Public room" : "Private invite"} · {roomPreview.code}
                </p>
                <h1>{roomPreview.name}</h1>
              </div>
              <span className={`invite-state-badge ${roomPreview.state}`}>
                {roomPreview.state === "playing" ? "In progress" : "Waiting"}
              </span>
            </div>

            <dl className="invite-room-facts">
              <div>
                <dt>Players</dt>
                <dd>
                  {roomPreview.playerCount}/{roomPreview.maxPlayers}
                  {roomPreview.isFull ? " · Full" : ""}
                </dd>
              </div>
              <div>
                <dt>Rounds</dt>
                <dd>{roomPreview.rounds}</dd>
              </div>
              <div>
                <dt>Draw time</dt>
                <dd>{roomPreview.drawingSeconds}s</dd>
              </div>
              <div>
                <dt>Scoring</dt>
                <dd>{roomPreview.scoringMode === "none" ? "Just for fun" : "Points on"}</dd>
              </div>
            </dl>

            <ul className="invite-rule-list" aria-label="Room rules">
              <li>{hintModeLabel(roomPreview)}</li>
              <li>
                {roomPreview.spectatorsSeeSolution
                  ? "Spectators can see the answer"
                  : "Spectators guess along"}
              </li>
              <li>
                {roomPreview.customWordCount > 0
                  ? `${roomPreview.customWordCount} custom words${
                      roomPreview.customWordsOnly ? " only" : " plus defaults"
                    }`
                  : "Default word list"}
              </li>
            </ul>

            {roomPreview.state === "playing" && (
              <p className="invite-callout">
                This game is already in progress. Joining as a player adds you to a future turn.
              </p>
            )}
            {entryNotice && <p className="invite-notice">{entryNotice}</p>}

            <form
              className="invite-join-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (!roomPreview.isFull) void handleEntryJoin(false);
              }}
            >
              <label htmlFor="invite-nickname">Your nickname</label>
              <input
                id="invite-nickname"
                type="text"
                value={nicknameInput}
                onChange={(event) => {
                  setNicknameInput(event.target.value);
                  setEntryError(null);
                }}
                maxLength={20}
                placeholder="Your name"
                autoComplete="nickname"
                autoFocus
                aria-describedby={entryError ? "invite-entry-error" : undefined}
              />
              {entryError && (
                <p id="invite-entry-error" className="invite-form-error" role="alert">
                  {entryError}
                </p>
              )}
              <div className="invite-actions">
                <button
                  type="submit"
                  className="invite-primary-button"
                  disabled={entryBusy || roomPreview.isFull}
                >
                  {roomPreview.isFull
                    ? "Room full"
                    : entryBusy
                    ? "Joining…"
                    : roomPreview.state === "playing"
                    ? "Join game in progress"
                    : "Join game"}
                </button>
                <button
                  type="button"
                  className={roomPreview.isFull ? "invite-primary-button" : "invite-secondary-button"}
                  disabled={entryBusy}
                  onClick={() => void handleEntryJoin(true)}
                >
                  {entryBusy ? "Joining…" : "Spectate"}
                </button>
              </div>
              {roomPreview.isFull && (
                <p className="invite-action-hint">Player slots are full. Spectating is still open.</p>
              )}
            </form>
          </main>
        )}
      </div>
    );
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
                brushWidth={activeWidth}
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
                  brushWidth={activeWidth}
                  onBrushWidthChange={handleWidthChange}
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
