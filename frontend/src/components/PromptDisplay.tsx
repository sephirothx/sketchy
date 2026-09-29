import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import { PHONE_LANDSCAPE_QUERY } from "../lib/roomLayout";
import { promptPickPayload } from "../lib/promptPick";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import { maskedWords, splitMaskedPrompt } from "../lib/maskedPrompt";
import type { AckResponse, HintMode } from "../types";
import { refusalText } from "../lib/refusals.ts";
import { applyPrivateResult } from "../lib/privateResults.ts";
import { ui } from "../content/ui/index.ts";

interface PromptDisplayProps {
  isDrawer: boolean;
  myPrompt: string | null;
  maskedPrompt: string;
  promptChoices: string[];
  promptChoicesTurnId?: string | null;
  revealedPrompt?: string | null;
  hintMode?: HintMode;
  canBuyHint?: boolean;
  nextHintCost?: number | null;
  letterPrices?: Record<string, number> | null;
  /** Points already committed to hints this turn, and the ceiling on them. */
  hintSpend?: number;
  maxHintSpend?: number;
}

// The server sends tightly spaced blanks per word, followed by the letter
// counts at the very end - one count per ALPHANUMERIC RUN, with punctuation
// as a boundary ("spider-man" reports "6 3"). The redesign renders each run
// as letter tiles with its count as a superscript numeral beside it (a
// multi-word prompt like "bow and arrow" reads ³ ³ ⁵, and "band-aid" reads
// ⁴-³). Purchasable slots keep the `.hint-blank` button contract, numbered
// across the whole prompt in run order to match the server's slot indices.
function renderMaskedPrompt(masked: string, buyableProps?: { canAfford: boolean; cost: number; busy: boolean; onBuy: (slot: number) => void }): ReactNode {
  const { blanks, counts } = splitMaskedPrompt(masked);

  if (counts.length === 0 && !blanks.includes("_")) {
    return <span className="prompt-blanks-text">{blanks}</span>;
  }

  const words = maskedWords(blanks);
  let run = -1;
  let slot = -1;

  return (
    <span className="masked-words" aria-label={ui.promptDisplay.maskedPrompt({ shape: counts.join(" and ") })}>
      {words.map((segments, wordIndex) => (
        <span key={wordIndex} className="masked-word">
          {segments.map((segment, segmentIndex) => {
            if (segment.kind === "glyph") {
              return (
                <span key={segmentIndex} className="masked-tile-glyph">
                  {segment.text}
                </span>
              );
            }
            run += 1;
            const count = counts[run];
            return (
              <span key={segmentIndex} className="masked-run">
                <span className="masked-tiles">
                  {segment.chars.map((ch, charIndex) => {
                    slot += 1;
                    if (ch === "_") {
                      if (buyableProps) {
                        const currentSlot = slot;
                        return (
                          <button
                            key={charIndex}
                            type="button"
                            className="masked-tile hint-blank"
                            disabled={!buyableProps.canAfford || buyableProps.busy}
                            aria-label={ui.promptDisplay.buyThisLetter({ cost: buyableProps.cost })}
                            title={ui.promptDisplay.buyThisLetter({ cost: buyableProps.cost })}
                            onClick={() => buyableProps.onBuy(currentSlot)}
                          />
                        );
                      }
                      return <span key={charIndex} className="masked-tile" />;
                    }
                    return (
                      <span key={charIndex} className="masked-tile is-revealed">
                        {ch}
                      </span>
                    );
                  })}
                </span>
                {count && (
                  <sup className="masked-word-count" aria-label={ui.promptDisplay.letterCount({ count: Number(count) })}>
                    {count}
                  </sup>
                )}
              </span>
            );
          })}
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
  promptChoicesTurnId = null,
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
  // Sideways, the wheel's 26 keys above the canvas left a guesser 18% of the
  // drawing (170 x 126 at 844 x 390): there they wait behind "Buy a letter",
  // over the canvas, and go once a letter is bought (#1267).
  const shortLandscape = useMediaQuery(PHONE_LANDSCAPE_QUERY);
  const [wheelOpen, setWheelOpen] = useState(false);
  const wheelId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  // Closing from inside - Escape, or a letter bought - hands the focus back to
  // the toggle rather than dropping it with the key that had it.
  function closeWheel(returnFocus: boolean) {
    setWheelOpen(false);
    if (returnFocus) requestAnimationFrame(() => toggleRef.current?.focus());
  }
  useEscapeLayer(wheelOpen, () => closeWheel(true));
  useEffect(() => {
    if (!wheelOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setWheelOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [wheelOpen]);
  // Only as tall as the screen below it: a short phone with the prompt's tiles
  // on two rows clipped the last keys out of reach. Past that it scrolls.
  useLayoutEffect(() => {
    const popover = popoverRef.current;
    if (!wheelOpen || !popover) return;
    const bottom = window.visualViewport?.height ?? window.innerHeight;
    popover.style.maxHeight = `${Math.max(120, Math.floor(bottom - popover.getBoundingClientRect().top - 8))}px`;
  }, [wheelOpen]);

  async function runAction(key: string, event: string, data: unknown, action: string) {
    if (pendingAction) return;
    setPendingAction(key);
    try {
      const response = await emitWithAck<AckResponse>(event, data);
      if (!response.ok) notify(refusalText(response, ui.promptDisplay.couldNotDoAction({ action })), "error");
      // A hint bought answers with what it revealed (#884).
      else applyPrivateResult(response);
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
          <p className="section-label">{ui.promptDisplay.yourTurn}</p>
          <h2 className="prompt-choice-title">{ui.promptDisplay.pickSomethingDraw}</h2>
          <p className="prompt-choice-hint">{ui.promptDisplay.autoPicksWhenTimeRunsOut}</p>
          <div className="prompt-choices">
            {/* Chosen by position, not by text (#1181): the text is how the
                drawer's language spells the offer. */}
            {promptChoices.map((prompt, index) => (
              <button key={prompt} disabled={pendingAction !== null} onClick={() => void runAction(`prompt:${index}`, "select_prompt", promptPickPayload(index, promptChoicesTurnId), ui.promptDisplay.selectThePrompt)}>
                {pendingAction === `prompt:${index}` ? ui.promptDisplay.choosing : prompt}
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
  const wheelBehindToggle = canBuyWheel && shortLandscape;
  // Turned to portrait, the turn over or the letters bought out: the popover
  // goes with its toggle rather than coming back open over the next turn.
  if (wheelOpen && !wheelBehindToggle) setWheelOpen(false);

  function letterGrid(inPopover: boolean) {
    return (
      <div className="wheel-letter-grid">
        {Object.entries(letterPrices ?? {})
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([letter, price]) => (
            <button
              key={letter}
              type="button"
              className="wheel-letter-btn"
              disabled={price > remaining || pendingAction !== null}
              title={ui.promptDisplay.buyLetter({ letter: letter.toUpperCase(), price })}
              onClick={() =>
                void runAction(`letter:${letter}`, "buy_wheel_letter", { letter }, ui.promptDisplay.buyTheLetterHint)
                  .then(() => {
                    if (inPopover) closeWheel(true);
                  })
              }
            >
              {letter.toUpperCase()}
              <sub>{price}</sub>
            </button>
          ))}
      </div>
    );
  }

  return (
    <div className={`prompt-display${wheelBehindToggle ? " has-wheel-toggle" : ""}`} ref={rootRef}>
      {(canBuy || canBuyWheel) && (
        <p className="hint-meta">
          {canBuy && (
            nextHintCost > remaining ? (
              <span className="hint-price-warning">{ui.promptDisplay.hintSpendLimitReached}</span>
            ) : (
              <span className="hint-price">{ui.promptDisplay.nextHintCost({ cost: nextHintCost })}</span>
            )
          )}
          {hintSpend > 0 && (
            <span
              className="hint-spend-total"
              title={ui.promptDisplay.hintSpendComesOutOfTurnPoints}
            >
              {ui.promptDisplay.hintSpendTotal({ spent: hintSpend })}
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
              onBuy: (slot) => void runAction(`hint:${slot}`, "buy_hint", { slot }, ui.promptDisplay.buyTheHint),
            } : undefined,
          )}
        </span>
      )}
      {wheelBehindToggle ? (
        <>
          <button
            ref={toggleRef}
            type="button"
            className="btn btn-secondary btn-compact wheel-hint-toggle"
            aria-expanded={wheelOpen}
            aria-controls={wheelOpen ? wheelId : undefined}
            onClick={() => setWheelOpen((open) => !open)}
          >
            {ui.promptDisplay.buyALetter}
          </button>
          {wheelOpen && (
            <div id={wheelId} ref={popoverRef} className="wheel-hint-popover" data-testid="wheel-hint-popover">
              <p className="hint-wheel-label">{ui.promptDisplay.buyLetterRevealsEveryMatch}</p>
              {letterGrid(true)}
            </div>
          )}
        </>
      ) : canBuyWheel && (
        <div className="wheel-hint-panel">
          <p className="hint-wheel-label">{ui.promptDisplay.buyLetterRevealsEveryMatch}</p>
          {letterGrid(false)}
        </div>
      )}
    </div>
  );
}
