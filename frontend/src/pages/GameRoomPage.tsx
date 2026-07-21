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
  const nextHintCost = useGameStore((s) => s.nextHintCost);
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
  const [brushWidth, setBrushWidth] = useState(4);
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

  function handleLeave() {
    socket.emit("leave_room");
    reset();
    navigate("/");
  }

  function handleStartGame() {
    emitWithAck("start_game", {});
  }

  const me = players.find((p) => p.token === token);
  const isHost = me?.isHost ?? false;
  const amDrawer =
    (phase === "drawing" || phase === "choosing_word") && drawerToken === token;
  const canDrawNow = phase === "drawing" && drawerToken === token;

  // Reset to the default color whenever a new drawing turn starts for this
  // player, instead of carrying over whatever color was last picked. Done
  // during render (rather than an effect) per React's "adjusting state when
  // a prop changes" pattern, to avoid an extra render pass.
  if (amDrawer !== wasDrawer) {
    setWasDrawer(amDrawer);
    if (amDrawer) {
      setColor("#000000");
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
      <header className="game-header">
        <h2>{roomName || code}</h2>
        <span className="room-code">
          Code: {code} ({isPublic ? "public" : "private"})
        </span>
        <button onClick={handleLeave}>Leave</button>
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
              <h3>Final scores</h3>
              <ol>
                {finalScores.map((s) => (
                  <li key={s.token}>
                    {s.nickname}: {s.score}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}

      {roomState === "playing" && (
        <div className="game-layout">
          <aside className="sidebar-left">
            <PlayerList players={players} drawerToken={drawerToken} />
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
            />
            <Canvas isDrawer={canDrawNow} color={color} brushWidth={brushWidth} tool={tool} />
            {phase === "round_end" && lastRoundResult && (
              <RoundEndOverlay
                word={lastRoundResult.word}
                drawerToken={lastRoundResult.drawerToken}
                scores={lastRoundResult.scores}
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
