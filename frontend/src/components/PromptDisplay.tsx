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
  maxHintSpend?: number;
}

// The server sends tightly spaced blanks per word, followed by each word's
// letter count (in order) at the very end; digits only appear in that count
// list, so splitMaskedPrompt separates the two. The redesign renders each
// word as a run of letter tiles with the word's letter count as a
// superscript numeral beside it (a multi-word prompt like "bow and arrow"
// reads ³ ³ ⁵). Purchasable slots keep the `.hint-blank` button contract.
function renderMaskedPrompt(masked: string, buyableProps?: { canAfford: boolean; cost: number; busy: boolean; onBuy: (slot: number) => void }): ReactNode {
  const { blanks, counts } = splitMaskedPrompt(masked);

  if (counts.length === 0 && !blanks.includes("_")) {
    return <span className="prompt-blanks-text">{blanks}</span>;
  }

  const words = blanks.trim().split(/\s+/);
  let slot = -1;

  return (
    <span className="masked-words" aria-label={`Masked prompt, ${counts.join(" and ")} letters`}>
      {words.map((word, wordIndex) => (
        <span key={wordIndex} className="masked-word">
          <span className="masked-tiles">
            {[...word].map((ch, charIndex) => {
              const isSlotChar = ch === "_" || /[a-zA-Z0-9]/.test(ch);
              if (isSlotChar) slot += 1;
              if (ch === "_") {
                if (buyableProps) {
                  const currentSlot = slot;
                  return (
                    <button
                      key={charIndex}
                      type="button"
                      className="masked-tile hint-blank"
                      disabled={!buyableProps.canAfford || buyableProps.busy}
                      title={`Buy this letter for ${buyableProps.cost} points`}
                      onClick={() => buyableProps.onBuy(currentSlot)}
                    />
                  );
                }
                return <span key={charIndex} className="masked-tile" />;
              }
              if (!isSlotChar) {
                return (
                  <span key={charIndex} className="masked-tile-glyph">
                    {ch}
                  </span>
                );
              }
              return (
                <span key={charIndex} className="masked-tile is-revealed">
                  {ch}
                </span>
              );
            })}
          </span>
          {counts[wordIndex] && (
            <sup className="masked-word-count" aria-label={`${counts[wordIndex]} letters`}>
              {counts[wordIndex]}
            </sup>
          )}
        </span>
      ))}
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
  maxHintSpend = 300,
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
        <div className="prompt-choice-card">
          <p className="section-label">Your turn</p>
          <h2 className="prompt-choice-title">Pick something to draw</h2>
          <p className="prompt-choice-hint">Auto-picks when time runs out.</p>
          <div className="prompt-choices">
            {promptChoices.map((prompt) => (
              <button key={prompt} disabled={pendingAction !== null} onClick={() => void runAction(`prompt:${prompt}`, "select_prompt", { prompt }, "select the prompt")}>
                {pendingAction === `prompt:${prompt}` ? "Choosing…" : prompt}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (maskedPrompt === "???" && !revealedPrompt && !isDrawer) {
    return null;
  }

  const canBuy = hintMode === "purchase" && canBuyHint && !isDrawer && !revealedPrompt && nextHintCost != null;
  const canBuyWheel = hintMode === "wheel" && canBuyHint && !isDrawer && !revealedPrompt && letterPrices != null;
  // Hints are bought on credit against this turn's guess, so the maximum spend
  // is independent of the running score.
  const remaining = maxHintSpend - hintSpend;

  return (
    <div className="prompt-display">
      {(canBuy || canBuyWheel) && (
        <p className="hint-meta">
          {canBuy && (
            nextHintCost > remaining ? (
              <span className="hint-price-warning">Hint spend limit reached</span>
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
