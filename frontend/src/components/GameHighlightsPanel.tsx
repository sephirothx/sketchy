import { useEscapeLayer } from "../hooks/useFocusTrap";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { presentHighlights } from "../lib/gameHighlights";
import type { GameHighlight } from "../types";

interface GameHighlightsPanelProps {
  highlights: GameHighlight[];
  onClose: () => void;
}

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
            <p className="game-highlights-kicker">Last game</p>
            <h1 id="game-highlights-title">Highlights</h1>
          </div>
          <button
            type="button"
            className="game-highlights-close"
            onClick={onClose}
            aria-label="Close highlights"
          >
            ✕
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
          <button type="button" onClick={onClose}>
            Back
          </button>
        </div>
      </section>
    </main>
  );
}
