import { useEffect, useState } from "react";
import type { RoundEndedPayload, RoundScoreEntry } from "../types";
import { playerNameClass, playerNameStyle } from "../lib/playerName";

interface RoundEndOverlayProps {
  word: string;
  drawerId: string;
  drawerBonus: number;
  myPlayerId: string | null;
  guesses?: RoundEndedPayload["guesses"];
  scores: RoundScoreEntry[];
  showScores?: boolean;
}

// Must match the height of .round-score-row in App.css - used to compute how
// far (in px) a row needs to slide from its previous rank position to its
// new one when animating overtakes.
const ROW_HEIGHT = 44;

function rankChange(entry: RoundScoreEntry) {
  const change = entry.previousRank - entry.newRank;
  if (change > 0) return { symbol: "\u25B2", places: change, className: "rank-up" };
  if (change < 0) return { symbol: "\u25BC", places: -change, className: "rank-down" };
  return null;
}

function formatGuessTime(seconds: number) {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;
}

export function RoundEndOverlay({
  word,
  drawerId,
  drawerBonus,
  myPlayerId,
  guesses = [],
  scores,
  showScores = true,
}: RoundEndOverlayProps) {
  // Rows render in their final (new-rank) order the whole time, but start
  // visually offset to where they *used* to rank. After a short pause (so
  // players have a moment to read the initial standings), we flip to
  // "settled" so the CSS transition slides each row into its real position -
  // players crossing paths as they overtake each other.
  const [settled, setSettled] = useState(false);

  useEffect(() => {
    const timeout = setTimeout(() => setSettled(true), 2000);
    return () => clearTimeout(timeout);
  }, []);

  const sorted = [...scores].sort((a, b) => a.newRank - b.newRank);
  const mine = sorted.find((entry) => entry.playerId === myPlayerId);

  return (
    <div
      className="round-end-overlay"
      role="status"
      aria-live="polite"
      aria-labelledby="round-end-title"
      data-testid="round-end-overlay"
    >
      <div className="round-end-panel">
        <h3 id="round-end-title">{showScores ? "Round results" : "Round complete"}</h3>
        <p className="round-end-word">
          The word was <strong>{word}</strong>
        </p>
        {showScores && mine && <p className="round-personal-result">Your round: <strong>{mine.delta >= 0 ? `+${mine.delta}` : mine.delta} points</strong> · now #{mine.newRank}</p>}
        {guesses.length > 0 ? (
          <>
            <h4 className="round-guesses-heading">Correct guesses</h4>
            <ol className="round-guesses-list">
              {guesses.map((guess) => (
                <li key={guess.playerId}>
                  <span
                    className={playerNameClass(guess.isAnonymous)}
                    style={playerNameStyle(guess.nameColor, guess.isAnonymous)}
                  >
                    {guess.nickname}
                  </span>
                  <time>{formatGuessTime(guess.seconds)}</time>
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className="round-no-guesses">No one guessed correctly.</p>
        )}
        {showScores && (
          <ul className="round-score-list">
            {sorted.map((entry) => {
              const change = rankChange(entry);
              const startOffset = (entry.previousRank - entry.newRank) * ROW_HEIGHT;
              return (
                <li
                  key={entry.playerId}
                  className="round-score-row"
                  style={{
                    transform: `translateY(${settled ? 0 : startOffset}px)`,
                    transition: settled ? "transform 600ms ease" : "none",
                  }}
                >
                  <span className="round-score-rank">#{entry.newRank}</span>
                  <span className="round-score-name">
                    {entry.playerId === drawerId ? "\u270F\uFE0F " : ""}
                    <span
                      className={playerNameClass(entry.isAnonymous)}
                      style={playerNameStyle(entry.nameColor, entry.isAnonymous)}
                    >
                      {entry.nickname}
                    </span>
                  </span>
                  {entry.playerId === drawerId && drawerBonus > 0 && <span className="drawer-bonus">🎨 +{drawerBonus}</span>}
                  {change && (
                    <span className={`round-score-change ${change.className}`}>
                      {change.symbol}
                      {change.places}
                    </span>
                  )}
                  <span className={`round-score-delta${entry.delta > 0 ? " positive" : ""}`}>
                    {entry.delta > 0 ? `+${entry.delta}` : entry.delta}
                  </span>
                  <span className="round-score-total">{entry.score}</span>
                  {entry.playerId === myPlayerId && <span className="round-score-you">You</span>}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
