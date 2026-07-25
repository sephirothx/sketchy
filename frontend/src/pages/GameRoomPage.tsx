import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Canvas } from "../components/Canvas";
import { Toolbar } from "../components/Toolbar";
import { PlayerList } from "../components/PlayerList";
import { WordDisplay } from "../components/WordDisplay";
import { Timer } from "../components/Timer";
import { GuessChat } from "../components/GuessChat";
import { RoundEndOverlay } from "../components/RoundEndOverlay";
import { emitWithAck, socket } from "../lib/socket";
import { splitMaskedWord } from "../lib/maskedWord";
import { useGameStore } from "../store/gameStore";
import type { AckResponse, DrawTool } from "../types";

export function GameRoomPage() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();

  const nickname = useGameStore((s) => s.nickname);
  const token = useGameStore((s) => s.token);
  const setSession = useGameStore((s) => s.setSession);
  const getStoredToken = useGameStore((s) => s.getStoredToken);
  const reset = useGameStore((s) => s.reset);

  const roomName = useGameStore((s) => s.name);
  const roomState = useGameStore((s) => s.roomState);
  const players = useGameStore((s) => s.players);
  const isPublic = useGameStore((s) => s.isPublic);
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

  if (joinError) {
    return (
      <div className="lobby-page">
        <p className="error-banner">{joinError}</p>
        <button onClick={() => navigate("/")}>Back to lobby</button>
      </div>
    );
  }

  return (
    <div className="game-room">
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
        <h2>{roomName || code}</h2>
        <span className="room-code">
          Code: {code} ({isPublic ? "public" : "private"} &middot;{" "}
          {scoringMode === "default" ? "default scoring" : "no scoring"})
        </span>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            style={{ background: me?.isAfk ? "#f59e0b" : undefined, color: me?.isAfk ? "#fff" : undefined }}
            onClick={handleToggleAfk}
          >
            {me?.isAfk ? "AFK 💤" : "AFK"}
          </button>
          <button onClick={handleLeave}>Leave</button>
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
            <PlayerList
              players={players}
              drawerToken={drawerToken}
              myToken={token}
              showScores={scoringMode === "default"}
            />
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
            <Canvas isDrawer={canDrawNow} color={color} brushWidth={brushWidth} tool={tool} />
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
            <GuessChat
              messages={messages}
              isDrawer={amDrawer}
              canGuess={phase === "drawing"}
              targetWordLengths={splitMaskedWord(maskedWord).counts}
            />
          </aside>
        </div>
      )}
    </div>
  );
}
