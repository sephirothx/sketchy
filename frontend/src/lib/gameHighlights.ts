import type { GameHighlight, HighlightName } from "../types";

/**
 * One highlight reduced to what the final screen draws: a label, a headline
 * figure, and - where the highlight belongs to someone - the name to render.
 *
 * Kept apart from the component so the wording and the rounding are testable
 * without mounting anything.
 */
export interface HighlightPresentation {
  kind: GameHighlight["kind"];
  label: string;
  value: string;
  prompt?: string;
  name?: HighlightName;
}

function seconds(value: number): string {
  // One decimal reads as a stopwatch; two reads as a measurement, and the
  // difference between 3.24s and 3.2s is not a thing anyone is comparing.
  return `${value.toFixed(1)}s`;
}

function percent(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

export function presentHighlight(highlight: GameHighlight): HighlightPresentation {
  switch (highlight.kind) {
    case "hardest_prompt":
      return {
        kind: highlight.kind,
        label: "Hardest prompt",
        value: `${highlight.correctGuessCount} of ${highlight.totalGuesserCount} guessed it`,
        prompt: highlight.prompt,
      };
    case "fastest_guess":
      return {
        kind: highlight.kind,
        label: "Fastest guess",
        value: seconds(highlight.seconds),
        prompt: highlight.prompt,
        name: highlight,
      };
    case "best_drawer":
      return {
        kind: highlight.kind,
        label: "Best drawer",
        value: `${percent(highlight.guessRatio)} guessed`,
        name: highlight,
      };
    case "quickest_average":
      return {
        kind: highlight.kind,
        label: "Quickest on average",
        value: seconds(highlight.seconds),
        name: highlight,
      };
  }
}

export function presentHighlights(
  highlights: GameHighlight[] | undefined,
): HighlightPresentation[] {
  return (highlights ?? []).map(presentHighlight);
}
