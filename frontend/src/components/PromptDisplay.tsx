import { useState, type ReactNode } from "react";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import { splitMaskedPrompt } from "../lib/maskedPrompt";
import type { AckResponse, HintMode } from "../types";

interface PromptDisplayProps {
  isDrawer: boolean;
  myPrompt: string | null;
  maskedPrompt: string;
  promptChoices: string[];
  revealedPrompt?: string | null;
  hintMode?: HintMode;
  canBuyHint?: boolean;
  nextHintCost?: number | null;
  letterPrices?: Record<string, number> | null;
  /** Points already committed to hints this turn, and the ceiling on them. */
  hintSpend?: number;
  hintBudget?: number;
}

// tightly spaced blanks per word, followed by each word's letter count (in
// order) at the very end. A prompt can be several words long, which is why
// there is a run of blanks and a count per word rather than one of each.
// Digits only ever appear in that trailing count list, so splitting on the
// first digit cleanly separates the two parts.
function renderMaskedPrompt(masked: string, buyableProps?: { canAfford: boolean; cost: number; busy: boolean; onBuy: (slot: number) => void }): ReactNode {
  const { blanks, counts } = splitMaskedPrompt(masked);
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
            disabled={!buyableProps.canAfford || buyableProps.busy}
            title={`Buy this letter for ${buyableProps.cost} points`}
            onClick={() => buyableProps.onBuy(currentSlot)}
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
    return <span className="prompt-blanks-text">{blanksNode}</span>;
  }

  const totalLength = counts.reduce((sum, c) => sum + (parseInt(c, 10) || 0), 0);
  const isLong = totalLength > 10 || blanks.length > 15;

  return (
    <span className={`masked-container ${isLong ? "is-long" : ""}`}>
      <span className="prompt-lengths">
        {counts.map((count, index) => (
          <sup key={index}>{count}</sup>
        ))}
      </span>
      <span className="prompt-blanks-text">{blanksNode}</span>
    </span>
  );
}

export function PromptDisplay({
  isDrawer,
  myPrompt,
  maskedPrompt,
  promptChoices,
  revealedPrompt,
  hintMode = "none",
  canBuyHint = false,
  nextHintCost = null,
  letterPrices = null,
  hintSpend = 0,
  hintBudget = 300,
}: PromptDisplayProps) {
  const { notify } = useToast();
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  async function runAction(key: string, event: string, data: unknown, action: string) {
    if (pendingAction) return;
    setPendingAction(key);
    try {
      const response = await emitWithAck<AckResponse>(event, data);
      if (!response.ok) notify(response.error || `Could not ${action}.`, "error");
    } catch (requestError) {
      notify(socketRequestErrorMessage(requestError, action), "error");
    } finally {
      setPendingAction(null);
    }
  }

  if (isDrawer && promptChoices.length > 0 && !myPrompt) {
    return (
      <div className="prompt-display choosing">
        <p>Choose a prompt to draw:</p>
        <div className="prompt-choices">
          {promptChoices.map((prompt) => (
            <button key={prompt} disabled={pendingAction !== null} onClick={() => void runAction(`prompt:${prompt}`, "select_prompt", { prompt }, "select the prompt")}>
              {pendingAction === `prompt:${prompt}` ? "Choosing…" : prompt}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (maskedPrompt === "???" && !revealedPrompt && !isDrawer) {
    return null;
  }

  const canBuy = hintMode === "purchase" && canBuyHint && !isDrawer && !revealedPrompt && nextHintCost != null;
  const canBuyWheel = hintMode === "wheel" && canBuyHint && !isDrawer && !revealedPrompt && letterPrices != null;
  // Hints are bought on credit against this turn's guess, so what limits them
  // is the turn's budget, not the running score.
  const remaining = hintBudget - hintSpend;

  return (
    <div className="prompt-display">
      {(canBuy || canBuyWheel) && (
        <p className="hint-meta">
          {canBuy && (
            nextHintCost > remaining ? (
              <span className="hint-price-warning">Budget spent</span>
            ) : (
              <span className="hint-price">Next hint: {nextHintCost}</span>
            )
          )}
          {hintSpend > 0 && (
            <span
              className="hint-spend-total"
              title="Deducted from your score if you guess the prompt"
            >
              Total: {hintSpend}
            </span>
          )}
        </p>
      )}
      {revealedPrompt ? (
        <span className="prompt-reveal">{revealedPrompt}</span>
      ) : isDrawer && (myPrompt || !maskedPrompt.includes("_")) ? (
        <span className="prompt-reveal">{myPrompt || maskedPrompt}</span>
      ) : (
        <span className="prompt-masked">
          {renderMaskedPrompt(
            maskedPrompt,
            canBuy ? {
              canAfford: nextHintCost <= remaining,
              cost: nextHintCost,
              busy: pendingAction !== null,
              onBuy: (slot) => void runAction(`hint:${slot}`, "buy_hint", { slot }, "buy the hint"),
            } : undefined,
          )}
        </span>
      )}
      {canBuyWheel && (
        <div className="wheel-hint-panel">
          <p className="hint-wheel-label">Buy a letter - reveals every match</p>
          <div className="wheel-letter-grid">
            {Object.entries(letterPrices)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([letter, price]) => (
                <button
                  key={letter}
                  type="button"
                  className="wheel-letter-btn"
                  disabled={price > remaining || pendingAction !== null}
                  title={`Buy "${letter.toUpperCase()}" for ${price} points`}
                  onClick={() => void runAction(`letter:${letter}`, "buy_wheel_letter", { letter }, "buy the letter hint")}
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
