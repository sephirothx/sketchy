import { useEffect, useState } from "react";
import type { ScoreEntry, ScoringMode } from "../types";

interface GameEndOverlayProps {
  scores: ScoreEntry[];
  myToken: string | null;
  scoringMode: ScoringMode;
  onContinue: () => void;
  drawingCount: number;
  onViewDrawings: () => void;
}

const PODIUM = ["🥇", "🥈", "🥉"];
const DISPLAY_SECONDS = 10;

export function GameEndOverlay({
  scores,
  myToken,
  scoringMode,
  onContinue,
  drawingCount,
  onViewDrawings,
}: GameEndOverlayProps) {
  const [remaining, setRemaining] = useState(DISPLAY_SECONDS);
  useEffect(() => {
    const timeout = setTimeout(onContinue, DISPLAY_SECONDS * 1000);
    const interval = setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => { clearTimeout(timeout); clearInterval(interval); };
  }, [onContinue]);

  const placement = scores.findIndex((score) => score.token === myToken) + 1;
  return <main className="game-end-overlay" aria-labelledby="game-end-title" aria-live="polite">
    <section className="game-end-podium">
      <p className="game-end-kicker">Game complete</p>
      <h1 id="game-end-title">{scoringMode === "default" ? <><span className="colored-player-name" style={{ color: scores[0]?.nameColor }}>{scores[0]?.nickname ?? "The room"}</span> takes the crown!</> : "A great round of drawing"}</h1>
      {scoringMode === "default" ? <><p className="game-end-placement">Your placement: #{Math.max(1, placement)}</p><ol className="game-end-scoreboard">{scores.map((score, index) => <li key={score.token} className={score.token === myToken ? "is-you" : ""}><span>{PODIUM[index] ?? `#${index + 1}`} <span className="colored-player-name" style={{ color: score.nameColor }}>{score.nickname}</span>{score.token === myToken ? " (you)" : ""}</span><strong>{score.score}</strong></li>)}</ol></> : <p className="game-end-no-score">No scores this time—just a room full of sketches and guesses.</p>}
      <div className="game-end-actions">
        {drawingCount > 0 && (
          <button type="button" onClick={onViewDrawings}>
            View drawings
          </button>
        )}
        <button type="button" onClick={onContinue}>Continue to waiting room · {remaining}s</button>
      </div>
    </section>
  </main>;
}
