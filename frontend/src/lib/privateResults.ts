/** A command's private result, handed from whoever sent the command to whoever
knows how to show it (#884).

A guess and a hint purchase used to be answered twice: an acknowledgement,
and then the events that carried what only this player sees -
`you_guessed_correctly`, `hint_revealed`, their own chat line, the verdict on
a near miss. The result now rides the acknowledgement, which is atomic with
it and one message where there were two to four. The sender (`socket.ts`,
`PromptDisplay`) has the answer; the game listeners know how to apply it
(confetti, sounds, the store). This joins the two without either importing
the other. */
import type { ChatMessage, GuessBreakdown } from "../types.ts";

export interface PrivateResult {
  /** A correct guess: the receipt `you_guessed_correctly` carried. */
  correct?: GuessBreakdown & { prompt: string };
  /** The acting player's own chat line. */
  line?: ChatMessage;
  /** The room's verdict on a near miss, an announcement. */
  verdict?: ChatMessage;
  /** A hint bought: what `hint_revealed` carried. */
  maskedPrompt?: string;
  hintCost?: number | null;
  letterPrices?: Record<string, number> | null;
  hintSpend?: number;
}

let apply: (result: PrivateResult) => void = () => {};

/** Registered by the game listeners, which own how a result is shown. */
export function providePrivateResultHandler(handler: (result: PrivateResult) => void): () => void {
  apply = handler;
  return () => {
    if (apply === handler) apply = () => {};
  };
}

/** Show a command's private result, if its acknowledgement carried one. */
export function applyPrivateResult(result: unknown): void {
  if (result && typeof result === "object") apply(result as PrivateResult);
}
