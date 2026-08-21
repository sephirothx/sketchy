import type { HintMode, ScoringMode } from "../types";

export const MAX_PLAYERS_MIN = 2;
export const MAX_PLAYERS_MAX = 16;
export const ROUNDS_MIN = 1;
export const ROUNDS_MAX = 10;
export const DRAWING_TIME_OPTIONS = [15, 30, 60, 90, 120, 180, 240, 300] as const;
export const DEFAULT_DRAWING_SECONDS = 90;
export const DEFAULT_HINT_MODE: HintMode = "checkpoints";

export const SCORING_OPTIONS: { value: ScoringMode; label: string; description: string }[] = [
  { value: "none", label: "No scoring", description: "No points are kept." },
  {
    value: "default",
    label: "Default",
    description: "Points fall steadily from 300 to 100 as the turn runs down.",
  },
  {
    value: "pressure",
    label: "Pressure",
    description:
      "Starts at 300 and drops ~2% a second, then twice as fast once someone gets the prompt.",
  },
];

export const HINT_OPTIONS: { value: HintMode; label: string; description: string }[] = [
  { value: "none", label: "No hints", description: "No letters are revealed during the turn." },
  {
    value: "checkpoints",
    label: "Timed hints",
    description: "Letters are revealed to everyone as the turn progresses.",
  },
  {
    value: "purchase",
    label: "Buy letters",
    description:
      "Uncover one letter position, visible only to you - the cost comes out of the points that turn's guess earns.",
  },
  {
    value: "wheel",
    label: "Wheel of Fortune",
    description:
      "Buy a letter and reveal every match for yourself - the cost comes out of the points that turn's guess earns.",
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
