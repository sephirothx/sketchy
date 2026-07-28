import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Canvas, type CanvasRef } from "../components/Canvas";
import { Toolbar } from "../components/Toolbar";
import { WordDisplay } from "../components/WordDisplay";
import { Timer } from "../components/Timer";
import { RoundEndOverlay } from "../components/RoundEndOverlay";
import { WaitingRoomPanel } from "../components/WaitingRoomPanel";
import { GameEndOverlay } from "../components/GameEndOverlay";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { ChoosingWordOverlay } from "../components/ChoosingWordOverlay";
import { RoomChatPanel } from "../components/RoomChatPanel";
import { RoomPlayersPanel } from "../components/RoomPlayersPanel";
import { RoomShell, type RoomShellMode } from "../components/RoomShell";
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

  const canvasRef = useRef<CanvasRef | null>(null);

  const nickname = useGameStore((s) => s.nickname);
  const setNickname = useGameStore((s) => s.setNickname);
  const token = useGameStore((s) => s.token);
  const activeRoomId = useGameStore((s) => s.roomId);
  const activeRoomCode = useGameStore((s) => s.code);
  const setSession = useGameStore((s) => s.setSession);
  const getStoredToken = useGameStore((s) => s.getStoredToken);
  const clearStoredToken = useGameStore((s) => s.clearStoredToken);
  const reset = useGameStore((s) => s.reset);

  const roomState = useGameStore((s) => s.roomState);
  const players = useGameStore((s) => s.players);
  const phase = useGameStore((s) => s.phase);
  const drawerToken = useGameStore((s) => s.drawerToken);
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
  const dismissGameEnd = useGameStore((s) => s.dismissGameEnd);

  const normalizedCode = code?.trim().toUpperCase() ?? "";
  const hasActiveSession = Boolean(
    token
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
  const [lastDrawing, setLastDrawing] = useState<string | null>(null);

  function saveLastDrawing() {
    if (!lastDrawing) return;
    const link = document.createElement("a");
    link.href = lastDrawing;
    link.download = "sketchy-last-drawing.png";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

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

    let cancelled = false;

    async function loadEntry() {
      try {
        const storedToken = getStoredToken(normalizedCode);
        if (storedToken) {
          const reconnect = await emitWithAck<AckResponse>("join_room", {
            code: normalizedCode,
            nickname,
            token: storedToken,
          });
          if (cancelled) return;
          if (reconnect.ok && reconnect.roomId && reconnect.code && reconnect.token) {
            setSession({
              roomId: reconnect.roomId,
              code: reconnect.code,
              token: reconnect.token,
            });
            return;
          }
          if (!reconnect.invalidToken) {
            setJoinError(reconnect.error || "Could not reconnect to this room");
            return;
          }
          clearStoredToken(normalizedCode);
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
        asSpectator,
      });

      if (response.ok && response.roomId && response.code && response.token) {
        setNickname(trimmedNickname);
        setSession({ roomId: response.roomId, code: response.code, token: response.token });
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
    function updateViewport() {
      const vv = window.visualViewport;
      const height = vv ? vv.height : window.innerHeight;
      document.documentElement.style.setProperty("--vv-height", `${height}px`);
      if (roomState === "playing") {
        window.scrollTo(0, 0);
      }
    }
    updateViewport();
    window.visualViewport?.addEventListener("resize", updateViewport);
    window.visualViewport?.addEventListener("scroll", updateViewport);
    window.addEventListener("resize", updateViewport);
    return () => {
      window.visualViewport?.removeEventListener("resize", updateViewport);
      window.visualViewport?.removeEventListener("scroll", updateViewport);
      window.removeEventListener("resize", updateViewport);
    };
  }, [roomState, phase]);

  useEffect(() => {
    function onKicked(data: { reason?: string }) {
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
  }, [navigate, notify, reset]);

  function performLeave() {
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

  useEffect(() => {
    if (phase === "round_end") setLastDrawing(canvasRef.current?.getImageDataUrl() ?? null);
  }, [phase]);

  function handleToggleAfk() {
    socket.emit("toggle_afk");
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

  const me = players.find((p) => p.token === token);
  const drawer = players.find((player) => player.token === drawerToken);
  const isHost = me?.isHost ?? false;
  const amDrawer =
    (phase === "drawing" || phase === "choosing_word") && drawerToken === token;
  const canDrawNow = phase === "drawing" && drawerToken === token;
  const canGuess = phase === "drawing" && !amDrawer && !(me?.isSpectator) && !guessedWord;

  // Active guess-focused mode applies ONLY on mobile screens (width <= 900px) when guessing during an active drawing round
  const isGuessFocused =
    isInputFocused && canGuess && phase === "drawing" && window.innerWidth <= 900;

  useEffect(() => {
    function alignGuessFocusedView() {
      if (window.innerWidth > 900) return;
      const vv = window.visualViewport;
      const el = document.querySelector(".game-room.guess-focused") as HTMLElement | null;
      if (vv && el) {
        el.style.position = "fixed";
        el.style.top = `${vv.offsetTop}px`;
        el.style.left = `${vv.offsetLeft}px`;
        el.style.width = `${vv.width}px`;
        el.style.height = `${vv.height}px`;
      }
    }

    if (isGuessFocused) {
      document.body.classList.add("guess-focused");
      document.documentElement.classList.add("guess-focused");
      alignGuessFocusedView();
      window.visualViewport?.addEventListener("resize", alignGuessFocusedView);
      window.visualViewport?.addEventListener("scroll", alignGuessFocusedView);
      window.addEventListener("resize", alignGuessFocusedView);
      return () => {
        const el = document.querySelector(".game-room") as HTMLElement | null;
        if (el) {
          el.style.position = "";
          el.style.top = "";
          el.style.left = "";
          el.style.width = "";
          el.style.height = "";
        }
        window.visualViewport?.removeEventListener("resize", alignGuessFocusedView);
        window.visualViewport?.removeEventListener("scroll", alignGuessFocusedView);
        window.removeEventListener("resize", alignGuessFocusedView);
        document.body.classList.remove("guess-focused");
        document.documentElement.classList.remove("guess-focused");
      };
    } else {
      const el = document.querySelector(".game-room") as HTMLElement | null;
      if (el) {
        el.style.position = "";
        el.style.top = "";
        el.style.left = "";
        el.style.width = "";
        el.style.height = "";
      }
      document.body.classList.remove("guess-focused");
      document.documentElement.classList.remove("guess-focused");
    }
  }, [isGuessFocused]);

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
  const isDrawerPerson = drawerToken === token;
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
    <div className={`game-room ${isGuessFocused ? "guess-focused" : ""}`}>
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
        <div>
          <button
            type="button"
            className="room-copy-button"
            onClick={() => void handleCopyLink()}
            title="Click to copy room invite link"
          >
            <span>Code: {code}</span>
          </button>
        </div>
        <div className="game-header-actions">
          <button
            type="button"
            className="game-header-afk-button"
            style={{ background: me?.isAfk ? "#f59e0b" : undefined, color: me?.isAfk ? "#fff" : undefined }}
            onClick={handleToggleAfk}
          >
            {me?.isAfk ? "AFK 💤" : "AFK"}
          </button>
          <button type="button" className="game-header-leave-button" onClick={handleLeave}>Leave</button>
          <button
            type="button"
            className="header-settings-button"
            onClick={openSettings}
            title="Game Settings"
          >
            <SettingsIcon size={16} />
            <span>Settings</span>
          </button>
        </div>
      </header>

      <RoomShell
        mode={roomView}
        players={
          <RoomPlayersPanel
            mode={roomView}
            players={players}
            drawerToken={drawerToken}
            myToken={token}
            maxPlayers={maxPlayers}
            showScores={scoringMode === "default"}
            finalScores={finalScores}
          />
        }
        playerFooter={
          roomView === "playing" ? (
            <div className="save-image-box">
              <button
                type="button"
                className="save-image-button"
                onClick={() => canvasRef.current?.saveImage()}
                title="Save drawn image to file"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                <span>Save Image</span>
              </button>
            </div>
          ) : undefined
        }
        main={
          roomView === "game-end" && finalScores ? (
            <GameEndOverlay
              scores={finalScores}
              myToken={token}
              scoringMode={scoringMode}
              onContinue={dismissGameEnd}
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
              myToken={token}
              isHost={isHost}
              finalScores={finalScores}
              startBusy={startBusy}
              startError={startError}
              onStart={() => void handleStartGame()}
              onLeave={handleLeave}
              onSaveDrawing={saveLastDrawing}
              hasDrawing={Boolean(lastDrawing)}
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
                    />
                  ) : null
                }
              />
              {phase === "round_end" && lastRoundResult && (
                <RoundEndOverlay
                  word={lastRoundResult.word}
                  drawerToken={lastRoundResult.drawerToken}
                  drawerBonus={lastRoundResult.drawerBonus}
                  guesses={lastRoundResult.guesses}
                  scores={lastRoundResult.scores}
                  myToken={token}
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
            mode={roomView}
            isDrawer={amDrawer}
            canGuess={canGuess}
            targetWordLengths={splitMaskedWord(maskedWord).counts}
            hideMaskedPrompt={hideMaskedPrompt}
            onFocusChange={setIsInputFocused}
          />
        }
      />
    </div>
  );
}
