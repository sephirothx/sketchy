import { describeDrawingRules } from "./drawingRules.ts";
import { HINT_OPTIONS, SCORING_OPTIONS, hintLabelFor, scoringLabelFor } from "./roomSetup.ts";
import type { ColorMode, DrawingToolGroup, HintMode, ScoringMode } from "../types.ts";

/**
 * One room, described the same way everywhere it is described (R-UX-09).
 *
 * A room used to be five different rooms: the lobby card counted players,
 * rounds and seconds; the invite page listed four facts and then three more
 * as prose; the waiting room had a one-line summary and an Edit link. Same
 * room, different facts, different order, so nothing a player learned in the
 * lobby survived the click.
 *
 * These six are it, in this order. Each carries four strings: a `label` for
 * the surfaces that name their facts, the `value` under that label, a `short`
 * form that reads on its own where there is no label to sit under, and a
 * `detail` saying what the fact means for the game about to be played.
 * Surfaces choose how much of that they have room for — the lobby card shows
 * three `short` forms, the waiting room all six with their details — but none
 * of them chooses *which* facts, or in what order.
 */
export type RoomFactKey =
  | "players"
  | "rounds"
  | "drawingTime"
  | "scoring"
  | "hints"
  | "drawingRules";

export interface RoomFact {
  key: RoomFactKey;
  label: string;
  value: string;
  /** The fact with no label above it: "3 rounds" rather than "3". */
  short: string;
  /** What the fact means for the game. Empty when the value says it all. */
  detail: string;
}

export interface RoomFactsInput {
  playerCount: number;
  maxPlayers: number;
  rounds: number;
  drawingSeconds: number;
  scoringMode: ScoringMode;
  hintMode: HintMode;
  hideMaskedPrompt: boolean;
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
}

/** The rough length the create page estimates: every player draws once per
 *  round, and a turn costs the drawing time plus choosing and results. */
export function estimatedMinutes(input: RoomFactsInput): number {
  const players = Math.max(2, input.playerCount);
  return Math.max(1, Math.round((players * input.rounds * (input.drawingSeconds + 24)) / 60));
}

export function roomFacts(input: RoomFactsInput): RoomFact[] {
  const seatsFree = Math.max(0, input.maxPlayers - input.playerCount);
  const minutes = estimatedMinutes(input);
  const players = Math.max(2, input.playerCount);
  const rules = describeDrawingRules(input.allowedTools, input.colorMode);
  return [
    {
      key: "players",
      label: "Players",
      value: `${input.playerCount} of ${input.maxPlayers}`,
      short: `${input.playerCount}/${input.maxPlayers}`,
      detail: seatsFree === 0 ? "the room is full" : `${seatsFree} ${seatsFree === 1 ? "seat" : "seats"} free`,
    },
    {
      key: "rounds",
      label: "Rounds",
      value: String(input.rounds),
      short: `${input.rounds} ${input.rounds === 1 ? "round" : "rounds"}`,
      detail: `everyone draws ${input.rounds === 1 ? "once" : `${input.rounds} times`}`,
    },
    {
      key: "drawingTime",
      label: "Drawing time",
      value: `${input.drawingSeconds}s`,
      short: `${input.drawingSeconds}s`,
      detail: `about ${minutes} min with ${players}`,
    },
    {
      key: "scoring",
      label: "Scoring",
      value: scoringLabelFor(input.scoringMode),
      short: input.scoringMode === "none" ? "No scoring" : `${scoringLabelFor(input.scoringMode)} scoring`,
      detail: SCORING_OPTIONS.find((option) => option.value === input.scoringMode)?.description ?? "",
    },
    {
      key: "hints",
      label: "Hints",
      value: hintLabelFor(input.hintMode, input.hideMaskedPrompt),
      short: hintLabelFor(input.hintMode, input.hideMaskedPrompt),
      detail: input.hideMaskedPrompt
        ? "Blanks are hidden, so there is nothing to reveal."
        : HINT_OPTIONS.find((option) => option.value === input.hintMode)?.description ?? "",
    },
    {
      key: "drawingRules",
      label: "Drawing rules",
      // Null from `describeDrawingRules` means the room restricts nothing,
      // which is a fact worth stating rather than a blank.
      value: rules ?? "All tools",
      short: rules ?? "All tools",
      detail: rules ? "" : "all colors",
    },
  ];
}

/** The whole room on one line, in the same order, for a summary row. The
 *  player count is left out: it is the one fact that changes by the second,
 *  and every surface using this shows it more prominently anyway. */
export function roomFactsSummary(input: RoomFactsInput): string {
  return roomFacts(input)
    .filter((fact) => fact.key !== "players")
    .map((fact) => fact.short)
    .join(" · ");
}
