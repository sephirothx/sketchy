/**
 * How the desktop drawing toolbar arranges its four groups in the width it has.
 *
 * The groups are the tools, the size, the palette and the canvas actions, and
 * the room's middle column never gives them one line: it runs from 293px at a
 * 901px window to 632px at the room's 1240px cap, against roughly 1050px for
 * all four side by side. Left to `flex-wrap` they broke wherever the pixels
 * ran out, so a divider could end a line or sit on one of its own, and below
 * about 426px the palette spilled out of the card (#781). The toolbar now
 * takes the first of a few arrangements, each designed to be seen, that fits
 * whole - and the phone's chip strip when none does.
 *
 * Chosen from measured widths rather than breakpoints, because what fits
 * depends on what the toolbar holds: the tools and colours the host allows,
 * the size readout and, most of all, the language - "Ongedaan maken" is three
 * times the length of "Undo". This module is the choice and nothing else, so
 * it can be tested without a DOM; `useToolbarLayout` does the measuring.
 */

export type ToolbarGroup = "tools" | "size" | "palette" | "actions";

export interface ToolbarArrangement {
  layout: "row" | "split" | "split-icons" | "stack";
  /** Lines, top to bottom, each a run of groups with a divider between neighbours. */
  rows: readonly (readonly ToolbarGroup[])[];
  /** Undo and Clear as icons alone, their names left to the tooltip and the accessible name. */
  iconActions: boolean;
}

/** Every arrangement, or the chip strip that stands in when none fits. */
export type ToolbarLayout = ToolbarArrangement["layout"] | "compact";

/**
 * In order of preference. Each one opens its first line with the tools and
 * then the size, which is what lets the space between two groups be measured
 * whichever arrangement is on screen.
 */
export const ARRANGEMENTS: readonly ToolbarArrangement[] = [
  // The mockup's single line, for a column that is ever wide enough.
  { layout: "row", rows: [["tools", "size", "palette", "actions"]], iconActions: false },
  // Everything that is pressed on one line, the palette under it.
  { layout: "split", rows: [["tools", "size", "actions"], ["palette"]], iconActions: false },
  // The same with Undo and Clear as icons: a third line under the canvas
  // costs the drawer more than two words do.
  { layout: "split-icons", rows: [["tools", "size", "actions"], ["palette"]], iconActions: true },
  // One group to a line once not even the icons fit beside the tools.
  { layout: "stack", rows: [["tools", "size"], ["palette"], ["actions"]], iconActions: false },
];

/** Widths in CSS pixels, measured off the rendered toolbar. */
export interface ToolbarMetrics {
  tools: number;
  size: number;
  palette: number;
  /** Undo and Clear with their names. */
  actions: number;
  /** Undo and Clear as icons alone. */
  actionIcons: number;
  /** Between two groups on one line: a gap, the divider, a gap. */
  separator: number;
  /** The card's own padding and border. */
  chrome: number;
}

export function arrangementOf(layout: ToolbarLayout): ToolbarArrangement | undefined {
  return ARRANGEMENTS.find((arrangement) => arrangement.layout === layout);
}

/** The width the card needs to show this arrangement with no line wrapping. */
export function arrangementWidth(arrangement: ToolbarArrangement, metrics: ToolbarMetrics): number {
  const widths: Record<ToolbarGroup, number> = {
    tools: metrics.tools,
    size: metrics.size,
    palette: metrics.palette,
    actions: arrangement.iconActions ? metrics.actionIcons : metrics.actions,
  };
  const lines = arrangement.rows.map(
    (row) => row.reduce((sum, group) => sum + widths[group], 0) + metrics.separator * (row.length - 1),
  );
  return metrics.chrome + Math.max(...lines);
}

/**
 * Held back from the column. Both sides of the comparison are fractional, and
 * a line that overshoots by a rounding error wraps its last group - the very
 * thing this module exists to prevent - so a tie goes to the next arrangement.
 */
const MARGIN = 0.5;

/** The first arrangement that fits in `available` pixels, or the chip strip. */
export function chooseToolbarLayout(metrics: ToolbarMetrics, available: number): ToolbarLayout {
  const fitting = ARRANGEMENTS.find(
    (arrangement) => arrangementWidth(arrangement, metrics) <= available - MARGIN,
  );
  return fitting?.layout ?? "compact";
}
