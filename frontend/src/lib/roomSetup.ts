import type { HintMode, ScoringMode } from "../types";

export const MAX_PLAYERS_MIN = 2;
export const MAX_PLAYERS_MAX = 16;
export const ROUNDS_MIN = 1;
export const ROUNDS_MAX = 10;
export const DRAWING_TIME_OPTIONS = [15, 30, 60, 90, 120, 180, 240, 300] as const;
export const DEFAULT_DRAWING_SECONDS = 90;
export const DEFAULT_HINT_MODE: HintMode = "checkpoints";

export const SCORING_OPTIONS: { value: ScoringMode; label: string }[] = [
  { value: "none", label: "Just for fun" },
  { value: "default", label: "Default" },
];

export const HINT_OPTIONS: { value: HintMode; label: string; description: string }[] = [
  { value: "none", label: "None", description: "No letters are revealed during the round." },
  {
    value: "checkpoints",
    label: "Timed hints",
    description: "Letters are revealed to everyone as the round progresses.",
  },
  {
    value: "purchase",
    label: "Buy letters",
    description: "Players spend points to uncover one letter position, visible only to them.",
  },
  {
    value: "wheel",
    label: "Wheel of Fortune",
    description: "Players spend points to buy a letter and reveal every match for themselves.",
  },
];
