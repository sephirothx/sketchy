import type { ReactNode } from "react";
import { emitWithAck } from "../lib/socket";
import { splitMaskedWord } from "../lib/maskedWord";
import type { HintMode } from "../types";

interface WordDisplayProps {
  isDrawer: boolean;
  myWord: string | null;
  maskedWord: string;
  wordChoices: string[];
  revealedWord?: string | null;
  hintMode?: HintMode;
  canBuyHint?: boolean;
  myScore?: number;
  nextHintCost?: number | null;
  letterPrices?: Record<string, number> | null;
}

// tightly spaced blanks per word, followed by each word's letter count (in
// order) at the very end. Digits only ever appear in that trailing count
// list, so splitting on the first digit cleanly separates the two parts.
function renderMaskedWord(masked: string, buyableProps?: { canAfford: boolean; cost: number }): ReactNode {
  const { blanks, counts } = splitMaskedWord(masked);
  let blanksNode: ReactNode = blanks;

  if (buyableProps) {
    const nodes: ReactNode[] = [];
    let buffer = "";
    let slot = -1;
    const flush = () => {
      if (buffer) {
        nodes.push(buffer);
        buffer = "";
      }
    };
    for (const ch of blanks) {
      const isSlotChar = ch === "_" || /[a-zA-Z0-9]/.test(ch);
      if (isSlotChar) slot += 1;
      if (ch === "_") {
        flush();
        const currentSlot = slot;
        nodes.push(
          <button
            key={nodes.length}
            type="button"
            className="hint-blank"
            disabled={!buyableProps.canAfford}
            title={`Buy this letter for ${buyableProps.cost} points`}
            onClick={() => emitWithAck("buy_hint", { slot: currentSlot })}
          >
            _
          </button>,
        );
      } else {
        buffer += ch;
      }
    }
    flush();
    blanksNode = nodes;
  }

  if (counts.length === 0) {
    return blanksNode;
  }
  return (
    <>
      {blanksNode}
      <span className="word-lengths">
        {counts.map((count, index) => (
          <sup key={index}>{count}</sup>
        ))}
      </span>
    </>
  );
}

export function WordDisplay({
  isDrawer,
  myWord,
  maskedWord,
  wordChoices,
  revealedWord,
  hintMode = "none",
  canBuyHint = false,
  myScore = 0,
  nextHintCost = null,
  letterPrices = null,
}: WordDisplayProps) {
  if (isDrawer && wordChoices.length > 0 && !myWord) {
    return (
      <div className="word-display choosing">
        <p>Choose a word to draw:</p>
        <div className="word-choices">
          {wordChoices.map((word) => (
            <button key={word} onClick={() => emitWithAck("select_word", { word })}>
              {word}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (maskedWord === "???" && !revealedWord && !isDrawer) {
    return null;
  }

  const canBuy = hintMode === "purchase" && canBuyHint && !isDrawer && !revealedWord && nextHintCost != null;
  const canBuyWheel = hintMode === "wheel" && canBuyHint && !isDrawer && !revealedWord && letterPrices != null;

  return (
    <div className="word-display">
      {canBuy && (
        <p className="hint-price">
          Click a blank to reveal it - costs <strong>{nextHintCost}</strong> pts
          {myScore < nextHintCost && <span className="hint-price-warning"> (not enough points)</span>}
        </p>
      )}
      {revealedWord ? (
        <span className="word-reveal">{revealedWord}</span>
      ) : isDrawer && (myWord || !maskedWord.includes("_")) ? (
        <span className="word-reveal">{myWord || maskedWord}</span>
      ) : (
        <span className="word-masked">
          {renderMaskedWord(
            maskedWord,
            canBuy ? { canAfford: myScore >= nextHintCost, cost: nextHintCost } : undefined,
          )}
        </span>
      )}
      {canBuyWheel && (
        <div className="wheel-hint-panel">
          <p className="hint-price">Buy a letter to reveal every occurrence:</p>
          <div className="wheel-letter-grid">
            {Object.entries(letterPrices)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([letter, price]) => (
                <button
                  key={letter}
                  type="button"
                  className="wheel-letter-btn"
                  disabled={myScore < price}
                  title={`Buy "${letter.toUpperCase()}" for ${price} points`}
                  onClick={() => emitWithAck("buy_wheel_letter", { letter })}
                >
                  {letter.toUpperCase()}
                  <sub>{price}</sub>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

