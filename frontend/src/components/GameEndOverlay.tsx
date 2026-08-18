import { useEffect, useState } from "react";
import type { ScoreEntry, ScoringMode } from "../types";
import { ColoredPlayerName } from "./ColoredPlayerName";
import { suggestUsername } from "../lib/username";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";

interface GameEndOverlayProps {
  scores: ScoreEntry[];
  myPlayerId: string | null;
  scoringMode: ScoringMode;
  onContinue: () => void;
  drawingCount: number;
  onViewDrawings: () => void;
}

const PODIUM = ["🥇", "🥈", "🥉"];
const DISPLAY_SECONDS = 10;

export function GameEndOverlay({
  scores,
  myPlayerId,
  scoringMode,
  onContinue,
  drawingCount,
  onViewDrawings,
}: GameEndOverlayProps) {
  const [remaining, setRemaining] = useState(DISPLAY_SECONDS);
  const [dismissedClaim, setDismissedClaim] = useState(false);
  const user = useAuthStore((state) => state.user);
  const openDialog = useAuthStore((state) => state.openDialog);
  const nickname = useGameStore((state) => state.nickname);
  const suggested = suggestUsername(nickname.trim() || user?.displayName || "");

  useEffect(() => {
    const timeout = setTimeout(onContinue, DISPLAY_SECONDS * 1000);
    const interval = setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => { clearTimeout(timeout); clearInterval(interval); };
  }, [onContinue]);

  const placement = scores.findIndex((score) => score.playerId === myPlayerId) + 1;
  const showClaim = Boolean(user?.isAnonymous) && !dismissedClaim;
  return <main className="game-end-overlay" aria-labelledby="game-end-title" aria-live="polite" data-testid="game-end-overlay">
    <section className="game-end-podium">
      <p className="game-end-kicker">Game complete</p>
      <h1 id="game-end-title">{scoringMode === "default" ? <><ColoredPlayerName nickname={scores[0]?.nickname ?? "The room"} nameColor={scores[0]?.nameColor} isAnonymous={scores[0]?.isAnonymous} /> takes the crown!</> : "A great round of drawing"}</h1>
      {scoringMode === "default" ? <><p className="game-end-placement">Your placement: #{Math.max(1, placement)}</p><ol className="game-end-scoreboard">{scores.map((score, index) => <li key={score.playerId} className={score.playerId === myPlayerId ? "is-you" : ""}><span>{PODIUM[index] ?? `#${index + 1}`} <ColoredPlayerName nickname={score.nickname} nameColor={score.nameColor} isAnonymous={score.isAnonymous} />{score.playerId === myPlayerId ? " (you)" : ""}</span><strong>{score.score}</strong></li>)}</ol></> : <p className="game-end-no-score">No scores this time—just a room full of sketches and guesses.</p>}
      {showClaim && (
        <div className="game-end-claim-banner">
          <p>
            {suggested
              ? `Playing as ${nickname || suggested}. Create an account to claim this name and keep your stats.`
              : "Create an account to keep your stats on any device."}
          </p>
          <div>
            <button type="button" onClick={() => openDialog("register")}>Create account</button>
            <button type="button" className="account-dialog-secondary" onClick={() => setDismissedClaim(true)}>Not now</button>
          </div>
        </div>
      )}
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
