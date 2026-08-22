import assert from "node:assert/strict";
import test from "node:test";

import {
  BLACK_AND_WHITE_COLORS,
  COLORBLIND_SAFE_COLORS,
  DEFAULT_ALLOWED_TOOLS,
  DEFAULT_COLOR_MODE,
  PALETTE_COLORS,
  allowsCustomColors,
  canDisallowTool,
  describeAllowedTools,
  describeDrawingRules,
  firstAllowedColor,
  firstAllowedTool,
  isColorAllowed,
  isPairedPalette,
  isToolAllowed,
  paletteForColorMode,
} from "../src/lib/drawingRules.ts";

test("the defaults take nothing away", () => {
  assert.deepEqual(DEFAULT_ALLOWED_TOOLS, ["brush", "fill", "shapes"]);
  assert.equal(DEFAULT_COLOR_MODE, "all");
  assert.equal(allowsCustomColors(DEFAULT_COLOR_MODE), true);
  assert.equal(describeDrawingRules(DEFAULT_ALLOWED_TOOLS, DEFAULT_COLOR_MODE), null);
});

test("the eraser rides with the brush and cannot be reached without it", () => {
  assert.equal(isToolAllowed("eraser", ["brush"]), true);
  assert.equal(isToolAllowed("eraser", ["shapes", "fill"]), false);
  assert.equal(isToolAllowed("brush", ["shapes", "fill"]), false);
});

test("each shape answers to the shapes chip", () => {
  for (const shape of ["rectangle", "ellipse", "triangle"]) {
    assert.equal(isToolAllowed(shape, ["shapes"]), true);
    assert.equal(isToolAllowed(shape, ["brush", "fill"]), false);
  }
});

test("every color mode keeps white, because white is the eraser", () => {
  for (const mode of ["all", "palette", "colorblind_safe", "black_and_white"]) {
    assert.equal(isColorAllowed("#ffffff", mode), true);
    assert.equal(isColorAllowed("#FFFFFF", mode), true);
  }
});

test("a restricted mode refuses a color off its palette", () => {
  assert.equal(isColorAllowed("#ed1c24", "black_and_white"), false);
  assert.equal(isColorAllowed("#ed1c24", "colorblind_safe"), false);
  assert.equal(isColorAllowed("#123456", "palette"), false);
  assert.equal(isColorAllowed("#123456", "all"), true);
});

test("only the default mode offers a custom color picker", () => {
  assert.equal(allowsCustomColors("all"), true);
  for (const mode of ["palette", "colorblind_safe", "black_and_white"]) {
    assert.equal(allowsCustomColors(mode), false);
  }
});

test("each mode shows its own swatches", () => {
  assert.deepEqual(paletteForColorMode("all"), PALETTE_COLORS);
  assert.deepEqual(paletteForColorMode("palette"), PALETTE_COLORS);
  assert.deepEqual(paletteForColorMode("colorblind_safe"), COLORBLIND_SAFE_COLORS);
  assert.deepEqual(paletteForColorMode("black_and_white"), BLACK_AND_WHITE_COLORS);
});

test("the colorblind-safe palette is not a subset of the built-in one", () => {
  const builtIn = new Set(PALETTE_COLORS);
  assert.ok(COLORBLIND_SAFE_COLORS.some((color) => !builtIn.has(color)));
});

test("the last of brush and shapes cannot be turned off", () => {
  assert.equal(canDisallowTool("brush", ["brush", "shapes"]), true);
  assert.equal(canDisallowTool("brush", ["brush", "fill"]), false);
  assert.equal(canDisallowTool("shapes", ["shapes"]), false);
  // Fill is never the one holding the room up
  assert.equal(canDisallowTool("fill", ["brush", "fill"]), true);
  // Nothing stops a chip that is already off from staying off
  assert.equal(canDisallowTool("fill", ["brush"]), true);
});

test("a fallback lands on something the room actually allows", () => {
  assert.equal(isToolAllowed(firstAllowedTool(["shapes", "fill"]), ["shapes", "fill"]), true);
  assert.equal(isToolAllowed(firstAllowedTool(["brush"]), ["brush"]), true);
  for (const mode of ["all", "palette", "colorblind_safe", "black_and_white"]) {
    assert.equal(isColorAllowed(firstAllowedColor(mode), mode), true);
  }
});

test("the tools read as a line, because a set has no name", () => {
  assert.equal(describeAllowedTools(["brush", "fill", "shapes"]), "All tools");
  assert.equal(describeAllowedTools(["brush"]), "Brush only");
  assert.equal(describeAllowedTools(["brush", "shapes"]), "Brush and Shapes");
  assert.equal(describeAllowedTools(["fill", "shapes"]), "Fill and Shapes");
  // Order follows the chips, not whatever order the server listed them in
  assert.equal(describeAllowedTools(["shapes", "brush"]), "Brush and Shapes");
});

test("only the rules that restrict something are described", () => {
  assert.equal(describeDrawingRules(["brush", "fill", "shapes"], "palette"), "Palette only");
  assert.equal(describeDrawingRules(["brush"], "all"), "Brush only");
  assert.equal(
    describeDrawingRules(["brush"], "black_and_white"),
    "Brush only, black and white",
  );
});

test("a summary from a server one deploy behind describes an unrestricted room", () => {
  // The types say these are always present; a rolling deploy says otherwise,
  // and a lobby card that throws takes the whole room list with it.
  assert.equal(describeDrawingRules(undefined, undefined), null);
  assert.equal(describeAllowedTools(undefined), "All tools");
  assert.equal(describeDrawingRules(undefined, "palette"), "Palette only");
  assert.equal(describeDrawingRules(["brush"], undefined), "Brush only");
});

test("only the built-in palette is laid out as light/dark pairs", () => {
  assert.equal(isPairedPalette("all"), true);
  assert.equal(isPairedPalette("palette"), true);
  // Okabe-Ito colors are chosen to be told apart, not to shade one another
  assert.equal(isPairedPalette("colorblind_safe"), false);
  assert.equal(isPairedPalette("black_and_white"), false);
});
