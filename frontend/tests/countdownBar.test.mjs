import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { barTransform } from "../src/lib/countdownBar.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

/** The declarations of the rule whose selector list is exactly `selector`. */
function rule(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`));
  assert.ok(match, `no rule for ${selector}`);
  return match[1];
}

test("a bar is slid, not sized: full, emptying and empty", () => {
  assert.equal(barTransform(1), "translateX(0%)");
  assert.equal(barTransform(0.25), "translateX(-75%)");
  assert.equal(barTransform(1.4), "translateX(0%)");
});

test("an empty bar is slid a pixel past its track, so no sliver shows", () => {
  for (const fraction of [0, -2, Number.NaN]) {
    assert.equal(barTransform(fraction), "translateX(calc(-100% - 1px))");
  }
});

test("neither countdown bar transitions or sets a width (#1256)", () => {
  // A width the compositor cannot run was a layout every frame: 155 layouts
  // in five idle seconds of a phone guesser's turn, 18% of the main thread
  // through a results phase.
  const bars = [
    [read("../src/styles/game-room.css"), ".timer-bar-fill"],
    [read("../src/styles/game-results.css"), ".turn-results-progress-track span"],
  ];
  for (const [css, selector] of bars) {
    const declarations = rule(css, selector);
    const transition = declarations.match(/transition:\s*([^;]*);/)[1];
    assert.match(transition, /\btransform\b/, `${selector} transitions transform`);
    assert.doesNotMatch(transition, /\bwidth\b/, `${selector} must not transition width`);
    assert.match(declarations, /\bwidth:\s*100%/, `${selector} is drawn full width and slid`);
  }
  // The slid-away part is hidden by its track, not drawn beside it.
  const tracks = [
    [read("../src/styles/game-room.css"), ".timer-bar-track"],
    [read("../src/styles/game-results.css"), ".turn-results-progress-track"],
  ];
  for (const [css, selector] of tracks) {
    assert.match(rule(css, selector), /\boverflow:\s*hidden;/, `${selector} clips its fill`);
  }
  for (const component of ["../src/components/Timer.tsx", "../src/components/TurnResultsOverlay.tsx"]) {
    const source = read(component);
    assert.doesNotMatch(source, /style=\{\{\s*width:/, `${component} must not size a bar`);
    assert.match(source, /barTransform\(/, `${component} slides its bar`);
  }
});

test("reduced motion still stops both bars' transitions", () => {
  assert.match(read("../src/styles/game-room.css"), /prefers-reduced-motion: reduce\)\s*\{\s*\.timer-bar-fill\s*\{\s*transition:\s*none;/);
  assert.match(
    read("../src/styles/game-results.css"),
    /prefers-reduced-motion: reduce\)\s*\{\s*\.turn-results-progress-track span\s*\{\s*transition:\s*none;/,
  );
});
