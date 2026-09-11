import type { HintMode, ScoringMode } from "../types";
import { ui } from "../content/ui/index.ts";

export const MAX_PLAYERS_MIN = 2;
export const MAX_PLAYERS_MAX = 16;
export const ROUNDS_MIN = 1;
export const ROUNDS_MAX = 10;
export const DRAWING_TIME_OPTIONS = [15, 30, 60, 90, 120, 180, 240, 300] as const;
export const DEFAULT_DRAWING_SECONDS = 90;
export const DEFAULT_HINT_MODE: HintMode = "checkpoints";

export const SCORING_OPTIONS: { value: ScoringMode; label: string; description: string }[] = [
  {
    value: "default",
    get label() { return ui.roomSetup.default; },
    get description() { return ui.roomSetup.fasterGuessesEarnMore100; },
  },
  {
    value: "pressure",
    get label() { return ui.roomSetup.pressure; },
    get description() { return ui.roomSetup.pointsDecayEverySecondTwice; },
  },
  { value: "none", get label() { return ui.roomSetup.noScoring; }, get description() { return ui.roomSetup.justDrawAndGuessNo; } },
];

export const HINT_OPTIONS: { value: HintMode; label: string; description: string }[] = [
  {
    value: "checkpoints",
    get label() { return ui.roomSetup.timedHints; },
    get description() { return ui.roomSetup.lettersRevealToEveryoneAt; },
  },
  { value: "none", get label() { return ui.roomSetup.noHints; }, get description() { return ui.roomSetup.blanksOnlyAllTurnLong; } },
  {
    value: "purchase",
    get label() { return ui.roomSetup.buyLetters; },
    get description() { return ui.roomSetup.revealALetterSlotJust; },
  },
  {
    value: "wheel",
    get label() { return ui.roomSetup.wheelOfFortune; },
    get description() { return ui.roomSetup.pickALetterPayIts; },
  },
];

/**
 * Is this number ready to be sent to the server?
 *
 * `InputNumber` reports every keystroke and only clamps on blur, so clearing
 * "8" to type "12" passes through 0 on the way. That is fine to show in the
 * field and fatal to send: the server refuses it and the host sees a revert
 * for something they were in the middle of typing. Out-of-range values wait
 * for the blur that clamps them.
 */
export function isSendableRoomNumber(
  field: "maxPlayers" | "rounds" | "drawingSeconds",
  value: number,
): boolean {
  if (!Number.isInteger(value)) return false;
  if (field === "drawingSeconds") return (DRAWING_TIME_OPTIONS as readonly number[]).includes(value);
  const [min, max] = field === "rounds"
    ? [ROUNDS_MIN, ROUNDS_MAX]
    : [MAX_PLAYERS_MIN, MAX_PLAYERS_MAX];
  return value >= min && value <= max;
}


/** The labels the collapsed sections, the create dock and the waiting room all
    use for these two, so the same room is described the same way wherever it
    is summarised. */
export function scoringLabelFor(mode: ScoringMode) {
  return SCORING_OPTIONS.find((option) => option.value === mode)?.label ?? ui.roomSetup.default;
}

/** A scoring mode named on its own in a summary - "Pressure scoring" - as a
whole phrase, since a label glued to an English noun is English in every
language but one. */
export function scoringNameFor(mode: ScoringMode): string {
  if (mode === "none") return ui.roomSetup.noScoring;
  return mode === "pressure" ? ui.roomSetup.pressureScoring : ui.roomSetup.defaultScoring;
}

export function hintLabelFor(hintMode: HintMode, hideMaskedPrompt: boolean) {
  return hideMaskedPrompt
    ? ui.roomSetup.hiddenPrompt
    : HINT_OPTIONS.find((option) => option.value === hintMode)?.label ?? ui.roomSetup.timedHints;
}
