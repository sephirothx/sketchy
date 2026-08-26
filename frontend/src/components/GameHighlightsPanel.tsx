import { useEscapeLayer } from "../hooks/useFocusTrap";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { presentHighlights } from "../lib/gameHighlights";
import { AlertIcon, BackIcon, BrushIcon, ClockIcon, XIcon, ZapIcon } from "./icons";
import { SectionLabel } from "./ui/Card";
import type { GameHighlight } from "../types";
import type { ReactNode } from "react";

interface GameHighlightsPanelProps {
  highlights: GameHighlight[];
  onClose: () => void;
}

const KIND_ICONS: Record<GameHighlight["kind"], ReactNode> = {
  hardest_prompt: <AlertIcon size={19} />,
  fastest_guess: <ZapIcon size={19} />,
  best_drawer: <BrushIcon size={19} />,
  quickest_average: <ClockIcon size={19} />,
};

/**
 * The finished game's highlights, on a screen of their own.
 *
 * Deliberately not folded into the game over screen. That screen is already
 * carrying a podium, the full standings, and sometimes a prompt to claim an
 * account, on a ten-second timer - and this is a list meant to grow. Given its
 * own room, a new highlight costs nothing to add.
 */
export function GameHighlightsPanel({ highlights, onClose }: GameHighlightsPanelProps) {
  useEscapeLayer(true, onClose);
  const presented = presentHighlights(highlights);

  return (
    <main className="game-highlights" aria-labelledby="game-highlights-title">
      <section className="game-highlights-card">
        <header className="game-highlights-header">
          <div>
            <SectionLabel className="game-highlights-kicker">Last game</SectionLabel>
            <h1 id="game-highlights-title">Highlights</h1>
          </div>
          <button
            type="button"
            className="game-highlights-close"
            onClick={onClose}
            aria-label="Close highlights"
          >
            <XIcon size={17} />
          </button>
        </header>

        {presented.length === 0 ? (
          <p className="game-highlights-empty">
            That game was too short to say much about. Play a longer one and the
            highlights will show up here.
          </p>
        ) : (
          <ul className="game-highlights-list">
            {presented.map((highlight) => (
              <li key={highlight.kind} className="game-highlights-item">
                <span className="game-highlights-icon" aria-hidden="true">
                  {KIND_ICONS[highlight.kind]}
                </span>
                <p className="game-highlights-label">{highlight.label}</p>
                <p className="game-highlights-subject">
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
                    <span className="game-highlights-prompt">
                      {highlight.name ? `(${highlight.prompt})` : highlight.prompt}
                    </span>
                  ) : null}
                </p>
                <p className="game-highlights-value">{highlight.value}</p>
              </li>
            ))}
          </ul>
        )}

        <div className="game-highlights-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            <BackIcon size={15} />
            Back
          </button>
        </div>
      </section>
    </main>
  );
}
