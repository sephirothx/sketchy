import { useEffect, useState, type ReactNode } from "react";
import type { GuessBreakdown, TurnEndedPayload, TurnScoreEntry } from "../types";
import { BrushIcon } from "./icons";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import {
  entranceDelays,
  hasPreviousOrder,
  rowStartOffsets,
} from "../lib/standings";

interface TurnResultsOverlayProps {
  prompt: string;
  drawerId: string;
  myPlayerId: string | null;
  guesses?: TurnEndedPayload["guesses"];
  scores: TurnScoreEntry[];
  showScores?: boolean;
  /** How my own turn score was arrived at, when I bought hints this turn. */
  myBreakdown?: GuessBreakdown | null;
  /** The results phase duration, driving the next-turn progress bar. */
  nextTurnSeconds?: number;
  nextTurnStartedAt?: number;
  /** The phase's full length. `nextTurnSeconds` is rebased to what remains
      when a sync arrives, so the bar's fraction divides by this instead. */
  nextTurnDurationSeconds?: number;
  /** The reaction control for the drawing these results are about. */
  reactions?: ReactNode;
}

// Must match the height of .turn-results-score-row in game-results.css - used to
// compute how far (in px) a row needs to slide from its previous rank position
// to its new one when animating overtakes. One value for every width: a
// breakpoint that changed it here and not there would slide rows to the wrong
// place on one of the two.
const ROW_HEIGHT = 38;

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
  myPlayerId,
  guesses = [],
  scores,
  showScores = true,
  myBreakdown = null,
  nextTurnSeconds = 0,
  nextTurnStartedAt = 0,
  nextTurnDurationSeconds = 0,
  reactions,
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

  useEffect(() => {
    // Rearranging waits, so the standings can be read before they move.
    // An entrance has nothing to read yet and should not keep players waiting.
    const timeout = setTimeout(() => setSettled(true), reordering ? 2000 : 250);
    return () => clearTimeout(timeout);
  }, [reordering]);

  // The bar is measured off the clock every tick rather than handed to a CSS
  // animation once. The animation was told a duration and a negative delay
  // computed at mount, so it drifted from the phase it was drawing: a delay
  // captured before `nextTurnStartedAt` arrived measured from the epoch and
  // drained the bar instantly, a sync mid-phase rebased the duration under an
  // animation that had already started, and nothing afterwards could correct
  // either. This is the same arithmetic the turn clock runs on.
  const [remaining, setRemaining] = useState(nextTurnSeconds);

  useEffect(() => {
    if (nextTurnSeconds <= 0 || !nextTurnStartedAt) return;
    const compute = () =>
      setRemaining(
        Math.max(0, nextTurnSeconds - (Date.now() - nextTurnStartedAt) / 1000),
      );
    compute();
    const interval = setInterval(compute, 100);
    return () => clearInterval(interval);
  }, [nextTurnSeconds, nextTurnStartedAt]);

  const progressDuration =
    nextTurnDurationSeconds > 0 ? nextTurnDurationSeconds : nextTurnSeconds;
  const progressFraction =
    progressDuration > 0 ? Math.max(0, Math.min(1, remaining / progressDuration)) : 0;

  // The order players got it in, to sit on their standings row. The list that
  // used to carry it repeated every name a second time under its own heading.
  const guessTimes = new Map(guesses.map((guess) => [guess.playerId, guess.seconds]));


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
        {reactions && <div className="turn-results-reactions">{reactions}</div>}
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
        {guesses.length === 0 && (
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
                  </span>
                  {guessTimes.has(entry.playerId) && (
                    <time className="turn-results-score-time">
                      {formatGuessTime(guessTimes.get(entry.playerId)!)}
                    </time>
                  )}
                  {change && (
                    <span className={`turn-results-score-change ${change.className}`}>
                      {change.symbol}
                      {change.places}
                    </span>
                  )}
                  {/* The brush is the whole of "they drew this turn": the row
                      used to say it twice, once as a pencil chip beside the
                      name and again as a bonus that the delta already
                      contained. */}
                  <span className={`turn-results-score-delta${entry.delta > 0 ? " positive" : ""}`}>
                    {entry.playerId === drawerId && (
                      <span className="turn-results-score-brush" title="Drew this turn">
                        <BrushIcon size={12} />
                      </span>
                    )}
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
              <span style={{ width: `${progressFraction * 100}%` }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
