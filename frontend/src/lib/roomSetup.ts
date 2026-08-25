import type { HintMode, ScoringMode } from "../types";

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
    label: "Default",
    description: "Faster guesses earn more, 100–300 points.",
  },
  {
    value: "pressure",
    label: "Pressure",
    description: "Points decay every second — twice as fast once someone guesses.",
  },
  { value: "none", label: "No scoring", description: "Just draw and guess. No standings." },
];

export const HINT_OPTIONS: { value: HintMode; label: string; description: string }[] = [
  {
    value: "checkpoints",
    label: "Timed hints",
    description: "Letters reveal to everyone at fixed times.",
  },
  { value: "none", label: "No hints", description: "Blanks only, all turn long." },
  {
    value: "purchase",
    label: "Buy letters",
    description: "Reveal a letter slot just for you — paid from that turn's points.",
  },
  {
    value: "wheel",
    label: "Wheel of Fortune",
    description: "Pick a letter, pay its price — vowels cost extra.",
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
