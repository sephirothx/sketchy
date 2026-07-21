import { useEffect, useState } from "react";
import type { RoundScoreEntry } from "../types";

interface RoundEndOverlayProps {
  word: string;
  drawerToken: string;
  scores: RoundScoreEntry[];
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

export function RoundEndOverlay({ word, drawerToken, scores }: RoundEndOverlayProps) {
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

  return (
    <div className="round-end-overlay">
      <div className="round-end-panel">
        <h3>Round results</h3>
        <p className="round-end-word">
          The word was <strong>{word}</strong>
        </p>
        <ul className="round-score-list">
          {sorted.map((entry) => {
            const change = rankChange(entry);
            const startOffset = (entry.previousRank - entry.newRank) * ROW_HEIGHT;
            return (
              <li
                key={entry.token}
                className="round-score-row"
                style={{
                  transform: `translateY(${settled ? 0 : startOffset}px)`,
                  transition: settled ? "transform 600ms ease" : "none",
                }}
              >
                <span className="round-score-rank">#{entry.newRank}</span>
                <span className="round-score-name">
                  {entry.token === drawerToken ? "\u270F\uFE0F " : ""}
                  {entry.nickname}
                </span>
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
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
