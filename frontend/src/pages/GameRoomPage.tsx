import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Canvas, type CanvasRef } from "../components/Canvas";
import { Toolbar } from "../components/Toolbar";
import { PlayerList } from "../components/PlayerList";
import { WordDisplay } from "../components/WordDisplay";
import { Timer } from "../components/Timer";
import { GuessChat } from "../components/GuessChat";
import { RoundEndOverlay } from "../components/RoundEndOverlay";
import { emitWithAck, socket } from "../lib/socket";
import { splitMaskedWord } from "../lib/maskedWord";
import { SettingsIcon } from "../components/SettingsIcon";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, DrawTool } from "../types";

export function GameRoomPage() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const openSettings = useSettingsStore((s) => s.openSettings);

  const canvasRef = useRef<CanvasRef | null>(null);

  const nickname = useGameStore((s) => s.nickname);
  const token = useGameStore((s) => s.token);
  const setSession = useGameStore((s) => s.setSession);
  const getStoredToken = useGameStore((s) => s.getStoredToken);
  const reset = useGameStore((s) => s.reset);

  const roomState = useGameStore((s) => s.roomState);
  const players = useGameStore((s) => s.players);
  const phase = useGameStore((s) => s.phase);
  const drawerToken = useGameStore((s) => s.drawerToken);
  const maskedWord = useGameStore((s) => s.maskedWord);
  const hintMode = useGameStore((s) => s.hintMode);
  const scoringMode = useGameStore((s) => s.scoringMode);
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

  const [joinError, setJoinError] = useState<string | null>(null);
  const [color, setColor] = useState("#000000");
  const [brushWidth, setBrushWidth] = useState(6);
  const [tool, setTool] = useState<DrawTool>("pen");
  const [wasDrawer, setWasDrawer] = useState(false);
  const [isInputFocused, setIsInputFocused] = useState(false);

  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    async function join() {
      const storedToken = getStoredToken(code!);
      const res = await emitWithAck<AckResponse>("join_room", {
        code,
        nickname: nickname || "Player",
        token: storedToken,
      });
      if (cancelled) return;
      if (res.ok && res.roomId && res.code && res.token) {
        setSession({ roomId: res.roomId, code: res.code, token: res.token });
      } else {
        setJoinError(res.error || "Could not join room");
      }
    }
    join();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

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

  const [notification, setNotification] = useState<string | null>(null);

  useEffect(() => {
    function onKicked(data: { reason?: string }) {
      reset();
      navigate("/", { state: { error: data?.reason || "You were kicked from the room." } });
    }
    function onVotedAfk(data: { message?: string }) {
      setNotification(data?.message || "You were marked AFK by room vote.");
    }
    socket.on("kicked", onKicked);
    socket.on("voted_afk", onVotedAfk);
    return () => {
      socket.off("kicked", onKicked);
      socket.off("voted_afk", onVotedAfk);
    };
  }, [navigate, reset]);

  function handleLeave() {
    socket.emit("leave_room");
    reset();
    navigate("/");
  }

  function handleToggleAfk() {
    socket.emit("toggle_afk");
  }

  function handleStartGame() {
    emitWithAck("start_game", {});
  }

  const me = players.find((p) => p.token === token);
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
    }
  }

  const spectatorsSeeSolution = useGameStore((s) => s.spectatorsSeeSolution);
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

  if (joinError) {
    return (
      <div className="join-error-container">
        <p className="error-banner">{joinError}</p>
        <button onClick={() => navigate("/")}>Back to lobby</button>
      </div>
    );
  }

  return (
    <div className={`game-room ${isGuessFocused ? "guess-focused" : ""}`}>
      {notification && (
        <div className="modal-overlay" onClick={() => setNotification(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-icon">💤</div>
            <h3 className="modal-title">Marked as AFK</h3>
            <p className="modal-body">{notification}</p>
            <button className="modal-button" onClick={() => setNotification(null)}>
              OK
            </button>
          </div>
        </div>
      )}
      <header className="game-header">
        <div>
          <span className="room-code">Code: {code}</span>
        </div>
        <div className="game-header-actions">
          <button
            style={{ background: me?.isAfk ? "#f59e0b" : undefined, color: me?.isAfk ? "#fff" : undefined }}
            onClick={handleToggleAfk}
          >
            {me?.isAfk ? "AFK 💤" : "AFK"}
          </button>
          <button onClick={handleLeave}>Leave</button>
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

      {roomState === "waiting" && (
        <div className="waiting-panel">
          <p>Waiting for players... ({players.length} joined)</p>
          {isHost && (
            <button disabled={players.length < 2} onClick={handleStartGame}>
              Start game
            </button>
          )}
          {finalScores && (
            <div className="game-end-panel">
              <h3>{scoringMode === "default" ? "Final scores" : "Game over!"}</h3>
              {scoringMode === "default" && (
                <ol>
                  {finalScores.map((s) => (
                    <li key={s.token}>
                      {s.nickname}: {s.score}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      )}

      {roomState === "playing" && (
        <div className="game-layout">
          <aside className="sidebar-left">
            <div className="sidebar-box">
              <PlayerList
                players={players}
                drawerToken={drawerToken}
                myToken={token}
                showScores={scoringMode === "default"}
              />
            </div>
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
          </aside>
          <main className="canvas-area">
            <div className="round-info">
              <span>
                Round {roundNumber}/{totalRounds}
              </span>
              <Timer totalSeconds={phaseSeconds} startedAt={phaseStartedAt} />
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
            />
            {phase === "round_end" && lastRoundResult && (
              <RoundEndOverlay
                word={lastRoundResult.word}
                drawerToken={lastRoundResult.drawerToken}
                guesses={lastRoundResult.guesses}
                scores={lastRoundResult.scores}
                showScores={scoringMode === "default"}
              />
            )}
            {canDrawNow && (
              <Toolbar
                color={color}
                onColorChange={setColor}
                brushWidth={brushWidth}
                onBrushWidthChange={setBrushWidth}
                tool={tool}
                onToolChange={setTool}
              />
            )}
          </main>
          <aside className="sidebar-right">
            <div className="sidebar-box">
              <GuessChat
                messages={messages}
                isDrawer={amDrawer}
                canGuess={canGuess}
                targetWordLengths={splitMaskedWord(maskedWord).counts}
                onFocusChange={setIsInputFocused}
              />
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
