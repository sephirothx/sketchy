import { useState, type ReactNode } from "react";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import { maskedPromptWords } from "../lib/maskedPrompt";
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

interface BuyableProps {
  canAfford: boolean;
  cost: number;
  busy: boolean;
  onBuy: (slot: number) => void;
}

// The masked prompt renders as letter tiles: one box per letter with revealed
// hints filled in, grouped per word, each word keeping its letter-run counts
// as a superscript so the length reads at a glance without counting boxes.
// A masked string that doesn't parse (see maskedPromptWords) falls back to
// the raw blanks-and-counts text so guessers never lose the prompt entirely.
function renderMaskedPrompt(masked: string, buyableProps?: BuyableProps): ReactNode {
  const words = maskedPromptWords(masked);
  if (!words) {
    return <span className="prompt-blanks-text">{masked}</span>;
  }

  const totalSlots = words.reduce(
    (sum, word) => sum + word.tiles.filter((tile) => tile.kind === "slot").length,
    0,
  );
  const isLong = totalSlots > 14;

  return (
    <span className={`masked-tiles${isLong ? " is-long" : ""}`}>
      {words.map((word, wordIndex) => (
        <span className="masked-word" key={wordIndex}>
          {word.tiles.map((tile, tileIndex) => {
            if (tile.kind === "literal") {
              return (
                <span className="masked-literal" aria-hidden="true" key={tileIndex}>
                  {tile.char}
                </span>
              );
            }
            if (tile.char !== null) {
              return (
                <span className="masked-tile is-revealed" key={tileIndex}>
                  {tile.char}
                </span>
              );
            }
            if (buyableProps && tile.slot !== null) {
              const currentSlot = tile.slot;
              return (
                <button
                  key={tileIndex}
                  type="button"
                  className="masked-tile hint-blank"
                  disabled={!buyableProps.canAfford || buyableProps.busy}
                  title={`Buy this letter for ${buyableProps.cost} points`}
                  aria-label={`Buy letter ${currentSlot + 1} for ${buyableProps.cost} points`}
                  onClick={() => buyableProps.onBuy(currentSlot)}
                />
              );
            }
            return <span className="masked-tile" aria-hidden="true" key={tileIndex} />;
          })}
          <sup className="masked-word-count" aria-hidden="true">
            {word.counts.join(" ")}
          </sup>
        </span>
      ))}
      <span className="visually-hidden">
        {`Masked prompt: ${words.map((word) => `${word.counts.join(" and ")} letters`).join(", ")}`}
      </span>
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
