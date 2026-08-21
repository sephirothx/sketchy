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
