import { useEffect, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { AuthDialog, type AuthMode } from "./AccountMenu";
import type { ScoreEntry, ScoringMode } from "../types";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { competitionRanks, crownOutcome, placementLabel } from "../lib/standings";

interface GameEndOverlayProps {
  scores: ScoreEntry[];
  myPlayerId: string | null;
  scoringMode: ScoringMode;
  onContinue: () => void;
  drawingCount: number;
  onViewDrawings: () => void;
  highlightCount: number;
  onViewHighlights: () => void;
}

const DISPLAY_SECONDS = 10;

export function GameEndOverlay({
  scores,
  myPlayerId,
  scoringMode,
  onContinue,
  drawingCount,
  onViewDrawings,
  highlightCount,
  onViewHighlights,
}: GameEndOverlayProps) {
  const [remaining, setRemaining] = useState(DISPLAY_SECONDS);
  const user = useAuthStore((state) => state.user);
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  // The strongest moment to ask: their result is on screen and there is now
  // something to lose.
  const isUnclaimedGuest = Boolean(user?.isAnonymous && user.displayName);

  useEffect(() => {
    // Hold the countdown while the claim form is open, or the overlay would
    // disappear from under someone mid-way through typing a password.
    if (authMode) return;
    const timeout = setTimeout(onContinue, DISPLAY_SECONDS * 1000);
    const interval = setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => { clearTimeout(timeout); clearInterval(interval); };
  }, [onContinue, authMode]);

  // Places, not row numbers: two players level on points tied for the same one.
  const ranks = competitionRanks(scores.map((score) => score.score));
  const myIndex = scores.findIndex((score) => score.playerId === myPlayerId);
  const placement = myIndex >= 0 ? ranks[myIndex] : 1;
  // A shared first has no single winner to crown, and saying otherwise would
  // contradict the two golds in the standings directly below.
  const winners = scores.filter((_score, index) => ranks[index] === 1);
  const crown = crownOutcome(winners.length);
  return <main className="game-end-overlay" aria-labelledby="game-end-title" aria-live="polite" data-testid="game-end-overlay">
    <section className="game-end-podium">
      <p className="game-end-kicker">Game over</p>
      <h1 id="game-end-title">
        {scoringMode === "none"
          ? "A great game of drawing"
          : crown === "room"
            ? "The room takes the crown!"
            : crown === "many"
              ? `${winners.length} players share the crown!`
              : <>
                  {winners.map((winner, index) => (
                    <span key={winner.playerId}>
                      {index > 0 ? (index === winners.length - 1 ? " and " : ", ") : ""}
                      <span
                        className={playerNameClass(winner.isAnonymous)}
                        style={playerNameStyle(winner.nameColor, winner.isAnonymous)}
                      >
                        {winner.nickname}
                      </span>
                    </span>
                  ))}
                  {crown === "one" ? " takes the crown!" : " share the crown!"}
                </>}
      </h1>
      {scoringMode !== "none" ? <><p className="game-end-placement">Your placement: #{Math.max(1, placement)}</p><ol className="game-end-standings">{scores.map((score, index) => <li key={score.playerId} className={score.playerId === myPlayerId ? "is-you" : ""}><span>{placementLabel(ranks[index])} <span className={playerNameClass(score.isAnonymous)} style={playerNameStyle(score.nameColor, score.isAnonymous)}>{score.nickname}</span>{score.playerId === myPlayerId ? " (you)" : ""}</span><strong>{score.score}</strong></li>)}</ol></> : <p className="game-end-no-score">No scores this time—just a room full of sketches and guesses.</p>}
      {isUnclaimedGuest && (
        <aside className="game-end-claim">
          <p className="game-end-claim-copy">
            <strong>{user!.displayName}</strong> isn’t saved. Create an account
            to keep it as your username.
          </p>
          <button
            type="button"
            className="game-end-claim-action"
            onClick={() => setAuthMode("claim")}
          >
            Create account
          </button>
        </aside>
      )}

      <div className="game-end-actions">
        {highlightCount > 0 && (
          <button type="button" onClick={onViewHighlights}>
            View highlights
          </button>
        )}
        {drawingCount > 0 && (
          <button type="button" onClick={onViewDrawings}>
            View drawings
          </button>
        )}
        <button type="button" onClick={onContinue}>
          Continue to waiting room{authMode ? "" : ` · ${remaining}s`}
        </button>
      </div>
    </section>
    {authMode && (
      <AuthDialog
        mode={authMode}
        suggestedUsername={user?.displayName ?? ""}
        onClose={() => setAuthMode(null)}
        onSwitchMode={setAuthMode}
        onSubmit={authMode === "login" ? login : register}
      />
    )}
  </main>;
}
