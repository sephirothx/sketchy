import { useEffect, useState } from "react";
import type { ScoreEntry, ScoringMode } from "../types";

interface GameEndOverlayProps {
  scores: ScoreEntry[];
  myToken: string | null;
  scoringMode: ScoringMode;
  onContinue: () => void;
}

const PODIUM = ["🥇", "🥈", "🥉"];
const DISPLAY_SECONDS = 6;

export function GameEndOverlay({ scores, myToken, scoringMode, onContinue }: GameEndOverlayProps) {
  const [remaining, setRemaining] = useState(DISPLAY_SECONDS);
  useEffect(() => {
    const timeout = setTimeout(onContinue, DISPLAY_SECONDS * 1000);
    const interval = setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => { clearTimeout(timeout); clearInterval(interval); };
  }, [onContinue]);

  const placement = scores.findIndex((score) => score.token === myToken) + 1;
  return <div className="game-end-overlay" role="dialog" aria-modal="true" aria-labelledby="game-end-title">
    <section className="game-end-podium">
      <p className="game-end-kicker">Game complete</p>
      <h1 id="game-end-title">{scoringMode === "default" ? `${scores[0]?.nickname ?? "The room"} takes the crown!` : "A great round of drawing"}</h1>
      {scoringMode === "default" ? <><p className="game-end-placement">Your placement: #{Math.max(1, placement)}</p><ol className="game-end-scoreboard">{scores.map((score, index) => <li key={score.token} className={score.token === myToken ? "is-you" : ""}><span>{PODIUM[index] ?? `#${index + 1}`} {score.nickname}{score.token === myToken ? " (you)" : ""}</span><strong>{score.score}</strong></li>)}</ol></> : <p className="game-end-no-score">No scores this time—just a room full of sketches and guesses.</p>}
      <button type="button" onClick={onContinue}>Continue to waiting room · {remaining}s</button>
    </section>
  </div>;
}
