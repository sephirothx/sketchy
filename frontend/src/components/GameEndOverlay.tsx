import { useEffect, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { AuthDialog, type AuthMode } from "./AccountMenu";
import type { GameHighlight, ScoreEntry, ScoringMode } from "../types";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { presentHighlights } from "../lib/gameHighlights";

interface GameEndOverlayProps {
  scores: ScoreEntry[];
  myPlayerId: string | null;
  scoringMode: ScoringMode;
  onContinue: () => void;
  drawingCount: number;
  onViewDrawings: () => void;
  highlights?: GameHighlight[];
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
  highlights,
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

  const placement = scores.findIndex((score) => score.playerId === myPlayerId) + 1;
  // Often shorter than four, and sometimes empty: the server drops any
  // highlight the game gave it nothing to say about.
  const presented = presentHighlights(highlights);
  return <main className="game-end-overlay" aria-labelledby="game-end-title" aria-live="polite" data-testid="game-end-overlay">
    <section className="game-end-podium">
      <p className="game-end-kicker">Game over</p>
      <h1 id="game-end-title">{scoringMode !== "none" ? <><span className={playerNameClass(scores[0]?.isAnonymous)} style={playerNameStyle(scores[0]?.nameColor, scores[0]?.isAnonymous)}>{scores[0]?.nickname ?? "The room"}</span> takes the crown!</> : "A great game of drawing"}</h1>
      {scoringMode !== "none" ? <><p className="game-end-placement">Your placement: #{Math.max(1, placement)}</p><ol className="game-end-standings">{scores.map((score, index) => <li key={score.playerId} className={score.playerId === myPlayerId ? "is-you" : ""}><span>{PODIUM[index] ?? `#${index + 1}`} <span className={playerNameClass(score.isAnonymous)} style={playerNameStyle(score.nameColor, score.isAnonymous)}>{score.nickname}</span>{score.playerId === myPlayerId ? " (you)" : ""}</span><strong>{score.score}</strong></li>)}</ol></> : <p className="game-end-no-score">No scores this time—just a room full of sketches and guesses.</p>}
      {presented.length > 0 && (
        <section className="game-end-highlights" aria-labelledby="game-end-highlights-title">
          <h2 id="game-end-highlights-title">Highlights</h2>
          <ul>
            {presented.map((highlight) => (
              <li key={highlight.kind}>
                <span className="game-end-highlight-label">{highlight.label}</span>
                <span className="game-end-highlight-subject">
                  {highlight.name ? (
                    <span
                      className={playerNameClass(highlight.name.isAnonymous)}
                      style={playerNameStyle(
                        highlight.name.nameColor,
                        highlight.name.isAnonymous,
                      )}
                    >
                      {highlight.name.nickname}
                    </span>
                  ) : null}
                  {highlight.prompt ? (
                    <span className="game-end-highlight-prompt">
                      {/* Parenthesised only next to a name: without them the two
                          run together as one phrase, on screen and when read. */}
                      {highlight.name ? `(${highlight.prompt})` : highlight.prompt}
                    </span>
                  ) : null}
                </span>
                <span className="game-end-highlight-value">{highlight.value}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

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
