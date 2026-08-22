import type { ColorMode, DrawTool, DrawingToolGroup } from "../types";

/**
 * The room's drawing rules, mirroring `backend/app/drawing_rules.py`.
 *
 * The server is authoritative: everything here hides a control the server
 * would refuse anyway, so that a drawer meets a rule as a missing button
 * rather than as a stroke that vanishes. `test_drawing_rules.py` fails if the
 * palettes on the two sides drift apart.
 */

export const DRAWING_TOOL_GROUPS = ["brush", "fill", "shapes"] as const;
export const DEFAULT_ALLOWED_TOOLS: DrawingToolGroup[] = ["brush", "fill", "shapes"];

/**
 * Which chip governs each tool.
 *
 * The eraser answers to the brush and cannot be separated from it: erasing is
 * a white brush stroke on the wire, so the server sees one action for both.
 */
const GROUP_BY_TOOL: Record<DrawTool, DrawingToolGroup> = {
  brush: "brush",
  eraser: "brush",
  fill: "fill",
  rectangle: "shapes",
  ellipse: "shapes",
  triangle: "shapes",
};

/** One of these has to stay selected: fill alone can only flood a blank canvas. */
export const TOOL_GROUPS_REQUIRING_ONE: DrawingToolGroup[] = ["brush", "shapes"];

export const TOOL_GROUP_OPTIONS: {
  value: DrawingToolGroup;
  label: string;
  description: string;
}[] = [
  { value: "brush", label: "Brush", description: "The brush and the eraser." },
  { value: "fill", label: "Fill", description: "The fill tool." },
  { value: "shapes", label: "Shapes", description: "Rectangle, ellipse, and triangle." },
];

/** Each pair is [light shade, dark shade] for the same color family. */
export const COLOR_PAIRS: readonly (readonly [string, string])[] = [
  ["#ffffff", "#000000"],
  ["#c1c1c1", "#4c4c4c"],
  ["#ed1c24", "#7f0000"],
  ["#ff7f27", "#a0522d"],
  ["#fff200", "#c9a227"],
  ["#b5e61d", "#2d5b1e"],
  ["#22b14c", "#1c6b5a"],
  ["#7ac9e8", "#2e5090"],
  ["#3f48cc", "#1b1b6e"],
  ["#a349a4", "#5c2d91"],
  ["#ec6ea8", "#7b3f61"],
  ["#ffae85", "#a9714b"],
  ["#c69c6d", "#5b3a1e"],
];

export const PALETTE_COLORS: readonly string[] = COLOR_PAIRS.flat();

/**
 * The Okabe-Ito set, plus white for the eraser. Not a subset of the palette
 * above: those pairs were chosen to look good and sit red next to green, so no
 * subset of them is genuinely safe.
 */
export const COLORBLIND_SAFE_COLORS: readonly string[] = [
  "#000000",
  "#e69f00",
  "#56b4e9",
  "#009e73",
  "#f0e442",
  "#0072b2",
  "#d55e00",
  "#cc79a7",
  "#ffffff",
];

export const BLACK_AND_WHITE_COLORS: readonly string[] = ["#000000", "#ffffff"];

/** What the client sends for an eraser stroke. Allowed under every color mode. */
export const ERASER_COLOR = "#ffffff";

export const DEFAULT_COLOR_MODE: ColorMode = "all";

export const COLOR_MODE_OPTIONS: {
  value: ColorMode;
  label: string;
  description: string;
}[] = [
  { value: "all", label: "All colors", description: "The palette and the custom color picker." },
  { value: "palette", label: "Palette only", description: "The built-in swatches; no custom colors." },
  {
    value: "colorblind_safe",
    label: "Colorblind-safe",
    description: "Colors that stay apart for colorblind players.",
  },
  { value: "black_and_white", label: "Black and white", description: "Black and white only." },
];

/** The swatches a mode offers. Every mode keeps white: it is the eraser. */
export function paletteForColorMode(mode: ColorMode): readonly string[] {
  if (mode === "colorblind_safe") return COLORBLIND_SAFE_COLORS;
  if (mode === "black_and_white") return BLACK_AND_WHITE_COLORS;
  return PALETTE_COLORS;
}

/**
 * Is this mode's palette laid out as light/dark pairs?
 *
 * The built-in thirteen are, and the toolbar stacks each pair in a column. The
 * colorblind-safe set is not - its colors are chosen to be told apart, not to
 * shade one another - so it reads as one flat row instead.
 */
export function isPairedPalette(mode: ColorMode): boolean {
  return mode === "all" || mode === "palette";
}

/** Does this mode let the drawer pick a color outside its palette? */
export function allowsCustomColors(mode: ColorMode): boolean {
  return mode === "all";
}

/**
 * Can this chip still be turned off? The last of brush and shapes cannot:
 * fill on its own leaves the room with nothing to draw with, and the server
 * refuses that set anyway.
 */
export function canDisallowTool(
  group: DrawingToolGroup,
  allowedTools: readonly DrawingToolGroup[],
): boolean {
  if (!allowedTools.includes(group)) return true;
  if (!TOOL_GROUPS_REQUIRING_ONE.includes(group)) return true;
  return allowedTools.filter((entry) => TOOL_GROUPS_REQUIRING_ONE.includes(entry)).length > 1;
}

export function isToolAllowed(tool: DrawTool, allowedTools: readonly DrawingToolGroup[]): boolean {
  return allowedTools.includes(GROUP_BY_TOOL[tool]);
}

export function isColorAllowed(color: string, mode: ColorMode): boolean {
  if (allowsCustomColors(mode)) return true;
  const normalized = color.toLowerCase();
  return normalized === ERASER_COLOR || paletteForColorMode(mode).includes(normalized);
}

/** The tool to fall back to when the drawer is holding one the room disallows. */
export function firstAllowedTool(allowedTools: readonly DrawingToolGroup[]): DrawTool {
  return allowedTools.includes("brush") ? "brush" : "rectangle";
}

/** The color to fall back to when the drawer is holding one the room disallows. */
export function firstAllowedColor(mode: ColorMode): string {
  return paletteForColorMode(mode)[allowsCustomColors(mode) ? 1 : 0] ?? "#000000";
}

/**
 * The room's tools in a line, for the room list, the invite preview, and the
 * waiting-room rules. Derived rather than stored: the setting is a set, and a
 * set has no name.
 *
 * Tolerates a summary with no rules on it, which the types say cannot happen
 * and a server one deploy behind this client sends anyway. Falling back to the
 * defaults describes that room as unrestricted, which is exactly what it is.
 */
export function describeAllowedTools(allowedTools?: readonly DrawingToolGroup[]): string {
  const selected = DRAWING_TOOL_GROUPS.filter(
    (group) => (allowedTools ?? DEFAULT_ALLOWED_TOOLS).includes(group),
  );
  if (selected.length === DRAWING_TOOL_GROUPS.length) return "All tools";
  const labels = selected.map(
    (group) => TOOL_GROUP_OPTIONS.find((option) => option.value === group)!.label,
  );
  if (labels.length === 1) return `${labels[0]} only`;
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

export function describeColorMode(mode?: ColorMode): string {
  return COLOR_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? "All colors";
}

/**
 * Both settings in one line, or null when the room restricts nothing - the
 * defaults are worth no words anywhere they are shown.
 */
export function describeDrawingRules(
  allowedTools?: readonly DrawingToolGroup[],
  mode?: ColorMode,
): string | null {
  const tools = allowedTools ?? DEFAULT_ALLOWED_TOOLS;
  const restrictsTools = tools.length !== DRAWING_TOOL_GROUPS.length;
  const restrictsColors = mode !== undefined && mode !== "all";
  if (!restrictsTools && !restrictsColors) return null;
  if (!restrictsColors) return describeAllowedTools(tools);
  if (!restrictsTools) return describeColorMode(mode);
  return `${describeAllowedTools(tools)}, ${describeColorMode(mode).toLowerCase()}`;
}
