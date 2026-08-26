import { useEffect, useState } from "react";
import type { GuessBreakdown, TurnEndedPayload, TurnScoreEntry } from "../types";
import { BrushIcon, PencilIcon } from "./icons";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import {
  entranceDelays,
  hasPreviousOrder,
  rowStartOffsets,
} from "../lib/standings";

interface TurnResultsOverlayProps {
  prompt: string;
  drawerId: string;
  drawerBonus: number;
  myPlayerId: string | null;
  guesses?: TurnEndedPayload["guesses"];
  scores: TurnScoreEntry[];
  showScores?: boolean;
  /** How my own turn score was arrived at, when I bought hints this turn. */
  myBreakdown?: GuessBreakdown | null;
  /** The results phase duration, driving the next-turn progress bar. */
  nextTurnSeconds?: number;
  nextTurnStartedAt?: number;
}

// Must match the height of .turn-results-score-row in App.css - used to compute how
// far (in px) a row needs to slide from its previous rank position to its
// new one when animating overtakes.
const ROW_HEIGHT = 44;

// How far left a row starts when it is introduced rather than rearranged.
const ENTRANCE_TRAVEL = 28;

function rankChange(entry: TurnScoreEntry) {
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

export function TurnResultsOverlay({
  prompt,
  drawerId,
  drawerBonus,
  myPlayerId,
  guesses = [],
  scores,
  showScores = true,
  myBreakdown = null,
  nextTurnSeconds = 0,
  nextTurnStartedAt = 0,
}: TurnResultsOverlayProps) {
  // Rows render in their final (new-rank) order the whole time, but start
  // visually offset to where they *used* to rank. After a short pause (so
  // players have a moment to read the initial standings), we flip to
  // "settled" so the CSS transition slides each row into its real position -
  // players crossing paths as they overtake each other.
  const sorted = [...scores].sort((a, b) => a.newRank - b.newRank);
  // Nothing to rearrange on the first turn: everyone came in level, so the
  // rows are introduced from the left instead, lowest place first.
  const reordering = hasPreviousOrder(sorted);
  const startOffsets = rowStartOffsets(sorted);
  const delays = entranceDelays(sorted.length);
  const mine = sorted.find((entry) => entry.playerId === myPlayerId);

  const [settled, setSettled] = useState(false);
  // Captured once on mount: how far into the results phase this client joined.
  const [progressOffsetSeconds] = useState(() =>
    Math.max(0, (Date.now() - nextTurnStartedAt) / 1000),
  );

  useEffect(() => {
    // Rearranging waits, so the standings can be read before they move.
    // An entrance has nothing to read yet and should not keep players waiting.
    const timeout = setTimeout(() => setSettled(true), reordering ? 2000 : 250);
    return () => clearTimeout(timeout);
  }, [reordering]);


  return (
    <div
      className="turn-results-overlay"
      role="status"
      aria-live="polite"
      aria-labelledby="turn-results-title"
      data-testid="turn-results-overlay"
    >
      <div className="turn-results-panel">
        <h3 id="turn-results-title">{showScores ? "Turn results" : "Turn complete"}</h3>
        <p className="turn-results-prompt">
          The prompt was <strong>{prompt}</strong>
        </p>
        {showScores && mine && (
          <p className="turn-results-personal">
            Your turn:{" "}
            {myBreakdown && myBreakdown.hintSpend > 0 ? (
              <strong>
                +{myBreakdown.basePoints}{" "}
                <span className="turn-results-hint-debt">-{myBreakdown.hintSpend} hints</span> ={" "}
                {myBreakdown.points} points
              </strong>
            ) : (
              <strong>{mine.delta >= 0 ? `+${mine.delta}` : mine.delta} points</strong>
            )}{" "}
            · now #{mine.newRank}
          </p>
        )}
        {guesses.length > 0 ? (
          <>
            <h4 className="turn-results-guesses-heading">Correct guesses</h4>
            <ol className="turn-results-guesses-list">
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
          <p className="turn-results-no-guesses">No one guessed correctly.</p>
        )}
        {showScores && (
          <ul className="turn-results-score-list">
            {sorted.map((entry, index) => {
              // A place lost only means something against a place held before.
              const change = reordering ? rankChange(entry) : null;
              const startOffset = startOffsets[index] * ROW_HEIGHT;
              const resting = {
                transform: "translate(0, 0)",
                opacity: 1,
              };
              const waiting = reordering
                ? { transform: `translateY(${startOffset}px)`, opacity: 1 }
                : { transform: `translateX(${-ENTRANCE_TRAVEL}px)`, opacity: 0 };
              return (
                <li
                  key={entry.playerId}
                  className="turn-results-score-row"
                  style={{
                    ...(settled ? resting : waiting),
                    transition: settled
                      ? reordering
                        ? "transform 600ms ease"
                        : "transform 420ms ease, opacity 420ms ease"
                      : "none",
                    transitionDelay:
                      settled && !reordering ? `${delays[index]}ms` : "0ms",
                  }}
                >
                  <span className="turn-results-score-rank">#{entry.newRank}</span>
                  <span className="turn-results-score-name">
                    <span
                      className={playerNameClass(entry.isAnonymous)}
                      style={playerNameStyle(entry.nameColor, entry.isAnonymous)}
                    >
                      {entry.nickname}
                    </span>
                    {entry.playerId === myPlayerId && (
                      <span className="turn-results-score-you"> (you)</span>
                    )}
                    {entry.playerId === drawerId && (
                      <span className="turn-results-drew" title="Drew this turn">
                        <PencilIcon size={12} />
                        drew
                      </span>
                    )}
                  </span>
                  {entry.playerId === drawerId && drawerBonus > 0 && (
                    <span className="drawer-bonus">
                      <BrushIcon size={12} /> +{drawerBonus}
                    </span>
                  )}
                  {change && (
                    <span className={`turn-results-score-change ${change.className}`}>
                      {change.symbol}
                      {change.places}
                    </span>
                  )}
                  <span className={`turn-results-score-delta${entry.delta > 0 ? " positive" : ""}`}>
                    {entry.delta > 0 ? `+${entry.delta}` : entry.delta}
                  </span>
                  <span className="turn-results-score-total">{entry.score}</span>
                </li>
              );
            })}
          </ul>
        )}
        {nextTurnSeconds > 0 && (
          <div className="turn-results-progress">
            <div className="turn-results-progress-labels">
              <span>Next turn</span>
            </div>
            <div className="turn-results-progress-track" aria-hidden="true">
              <span
                style={{
                  animationDuration: `${nextTurnSeconds}s`,
                  animationDelay: `-${progressOffsetSeconds}s`,
                }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
