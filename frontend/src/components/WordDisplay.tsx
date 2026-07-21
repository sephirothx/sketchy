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

  const canBuy = hintMode === "purchase" && canBuyHint && !isDrawer && !revealedWord && nextHintCost != null;

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
      ) : isDrawer && myWord ? (
        <span className="word-reveal">{myWord}</span>
      ) : (
        <span className="word-masked">
          {renderMaskedWord(
            maskedWord,
            canBuy ? { canAfford: myScore >= nextHintCost, cost: nextHintCost } : undefined,
          )}
        </span>
      )}
    </div>
  );
}

