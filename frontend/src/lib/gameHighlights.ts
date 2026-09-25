import type { GameHighlight, HighlightName } from "../types";
import { ui } from "../content/ui/index.ts";
import { formatGuessTime } from "./guessTime.ts";

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
  /** Where in the recap the card can take you, when it is about a drawing. */
  drawingIndex?: number;
}

function percent(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

export function presentHighlight(highlight: GameHighlight): HighlightPresentation {
  switch (highlight.kind) {
    case "hardest_prompt":
      return {
        kind: highlight.kind,
        label: ui.gameHighlights.hardestPrompt,
        value: ui.gameHighlights.guessedItOf({
          correct: highlight.correctGuessCount,
          total: highlight.totalGuesserCount,
        }),
        prompt: highlight.prompt,
      };
    case "fastest_guess":
      return {
        kind: highlight.kind,
        label: ui.gameHighlights.fastestGuess,
        // The chat line, the players panel and the results card's formatter,
        // so the game's fastest guess reads as it did when it landed.
        value: formatGuessTime(highlight.seconds),
        prompt: highlight.prompt,
        name: highlight,
      };
    case "best_drawer":
      return {
        kind: highlight.kind,
        label: ui.gameHighlights.bestDrawer,
        value: ui.gameHighlights.percentGuessed({ percent: percent(highlight.guessRatio) }),
        name: highlight,
      };
    case "quickest_average":
      return {
        kind: highlight.kind,
        label: ui.gameHighlights.quickestOnAverage,
        value: formatGuessTime(highlight.seconds),
        name: highlight,
      };
    case "most_reacted_drawing":
      return {
        kind: highlight.kind,
        label: ui.gameHighlights.mostReactedDrawing,
        value: ui.gameHighlights.reactionCount({ count: highlight.reactionCount }),
        prompt: highlight.prompt,
        name: highlight,
        drawingIndex: highlight.drawingIndex,
      };
  }
}

export function presentHighlights(
  highlights: GameHighlight[] | undefined,
): HighlightPresentation[] {
  return (highlights ?? []).map(presentHighlight);
}
