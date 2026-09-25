/** The stylesheets' scales stay on their tokens (C10, D5).

Nothing else notices a scale drifting. A 7px radius beside an 8px one, a
140ms hover beside a 150ms one, a label tracked 0.07em beside one at 0.09em:
each is invisible alone, and the browser is as happy with the hundredth as
with the first. A weight the page never loaded is worse - it renders as the
nearest weight that was loaded, silently, so the stylesheet says one thing and
the screen another. So this reads every stylesheet and fails on a value off
its scale, and each exception is named below with the reason it is one.

The scales live in `src/styles/theme.css`; the recipe for the one capitals
style is `.section-label` in `src/styles/primitives.css`.
*/
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const STYLES = "src/styles";

/** Every innermost rule in every stylesheet: its file, line, selector and
 *  declarations. Innermost is enough - an @media block's rules are found
 *  inside it, and nothing here declares a property on the at-rule itself. */
function rules() {
  const found = [];
  for (const file of readdirSync(STYLES).filter((name) => name.endsWith(".css"))) {
    const source = readFileSync(join(STYLES, file), "utf8");
    // Comments blanked rather than removed, so offsets still give lines.
    const text = source.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, " "));
    for (const match of text.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
      const selector = match[1].replace(/\s+/g, " ").trim();
      if (selector.startsWith("@")) continue;
      const line = text.slice(0, match.index + match[0].length - match[2].length - 1).split("\n").length;
      const declarations = new Map();
      for (const part of match[2].split(";")) {
        const colon = part.indexOf(":");
        if (colon < 0) continue;
        declarations.set(part.slice(0, colon).trim(), part.slice(colon + 1).trim());
      }
      found.push({ file, line, selector, declarations, where: `${file}:${line} ${selector}` });
    }
  }
  return found;
}

const RULES = rules();

function offScale(check) {
  return RULES.flatMap((rule) => check(rule) ?? []);
}

test("every radius is a token, a circle, or a named exception", () => {
  const allowed = new Set([
    "0",
    "50%",
    "inherit",
    // Marks smaller than the smallest step: slider stops, the grab bar,
    // highlight and focus insets, badges drawn at icon size.
    "1px",
    "3px",
    "4px",
    // The bottom sheet's top edge, which is a sheet, not a card.
    "24px 24px 0 0",
    // Half of one row's height on a segmented control that wraps to two rows
    // (create-room-page.css says why a pill would be wrong there).
    "18.5px",
  ]);
  const bad = offScale((rule) =>
    [...rule.declarations]
      .filter(([property]) => property === "border-radius" || /^border-.*-radius$/.test(property))
      .filter(([, value]) => {
        const bare = value.replace(/\s*!important$/, "");
        if (allowed.has(bare)) return false;
        return !bare.split(/\s+/).every((part) => part === "0" || /^var\(--radius(-xs|-sm|-pill)?\)$/.test(part));
      })
      .map(([, value]) => `${rule.where}: ${value}`),
  );
  assert.deepEqual(bad, [], "use --radius, --radius-sm, --radius-xs or --radius-pill");
});

test("transitions and animations name their properties and use the motion tokens", () => {
  // A transition that joins the steps of a clock follows that clock's
  // cadence, not the motion scale.
  const clocked = new Set([
    ".timer-bar-fill", // Timer.tsx recomputes the width every 250ms
    ".turn-results-progress-track span", // the phase clock ticks every 100ms
  ]);
  // Animations whose length is part of what they show rather than how fast
  // something arrives, named by keyframes.
  const timed = new Map([
    ["gallery-spin", "a loading spinner's period, one turn"],
    ["invite-spin", "a loading spinner's period, one turn"],
    ["choosing-prompt-pulse", "a looping pulse's period"],
    ["reaction-float", "how long a reaction drifts up the canvas before it fades"],
    ["restart-approved-emphasis", "the approved banner's one beat of emphasis"],
    ["rank-change-pop", "a 300ms pop delayed 2550ms, both timed against the results rows' 420/600ms entrance so it lands as they settle"],
  ]);
  const literal = (value) =>
    value.split(",").filter((part) => /(?<![\w-])\d*\.?\d+m?s\b/.test(part));
  const badAnimations = offScale((rule) =>
    ["animation", "animation-duration"].flatMap((property) => {
      const value = rule.declarations.get(property);
      if (!value || value.startsWith("none")) return [];
      return literal(value)
        .filter((part) => !timed.has(part.trim().split(/\s+/)[0]))
        .map((part) => `${rule.where}: ${property}: ${part.trim()}`);
    }),
  );
  const badDurations = offScale((rule) => {
    const value = rule.declarations.get("transition-duration");
    return value && literal(value).length ? [`${rule.where}: transition-duration: ${value}`] : [];
  });
  const bad = offScale((rule) => {
    const value = rule.declarations.get("transition");
    if (!value || value === "none" || value.startsWith("none ")) return [];
    if (/\ball\b/.test(value)) return [`${rule.where}: transition: all animates whatever changes next`];
    // The autofill wash: a delay long enough that the browser's yellow
    // never arrives, which is not a motion at all.
    if (rule.selector.startsWith("input:-webkit-autofill")) return [];
    return literal(value)
      .filter((part) => !(clocked.has(rule.selector) && /^\s*width /.test(part)))
      .map((part) => `${rule.where}: ${part.trim()}`);
  });
  assert.deepEqual(
    [...bad, ...badDurations, ...badAnimations],
    [],
    "use var(--dur-fast) or var(--dur), and list the properties that change",
  );
});

test("a disabled control dims by the one amount", () => {
  const allowed = new Map([
    // Cancels the dimming on purpose: a revealed letter tile and a switch's
    // hint stay readable while the control is off.
    ["1", null],
    // The only selected list, which cannot be unselected: locked on, not
    // unavailable (create-room-page.css says why).
    ["0.85", ".toggle-chip:disabled"],
  ]);
  const bad = offScale((rule) => {
    if (!/:disabled|\.is-disabled/.test(rule.selector)) return [];
    const value = rule.declarations.get("opacity");
    if (!value || value === "var(--opacity-disabled)") return [];
    if (allowed.has(value) && [null, rule.selector].includes(allowed.get(value))) return [];
    return [`${rule.where}: opacity ${value}`];
  });
  assert.deepEqual(bad, [], "use var(--opacity-disabled)");
});

test("every weight asked for is a weight the page loads", () => {
  const main = readFileSync("src/main.tsx", "utf8");
  const loaded = (family) =>
    new Set([...main.matchAll(new RegExp(`@fontsource/${family}/(\\d+)\\.css`, "g"))].map((match) => match[1]));
  const body = loaded("nunito-sans");
  const display = loaded("fredoka");
  assert.ok(body.size > 0 && display.size > 0, "main.tsx no longer loads the fonts this test expects");
  const named = { normal: "400", bold: "700" };

  const bad = offScale((rule) => {
    const weight = rule.declarations.get("font-weight");
    if (!weight || weight === "inherit") return [];
    const numeric = named[weight] ?? weight;
    const family = rule.declarations.get("font-family") ?? "";
    // reset.css gives every heading the display face; a rule on a heading
    // that does not name a face of its own is in that face.
    const lastCompound = rule.selector.split(",").map((part) => part.trim().split(/[\s>+~]+/).pop());
    const onHeading = lastCompound.every((compound) => /^h[1-6]\b/.test(compound));
    const isDisplay = family.includes("--font-display") || (!family && onHeading);
    // The one Fredoka rule this cannot see: the first-run name field's
    // placeholder inherits the field's display face.
    if (rule.selector === ".first-run-guest-row input::placeholder") {
      return display.has(numeric) ? [] : [`${rule.where}: ${weight} (Fredoka)`];
    }
    const faces = isDisplay ? display : body;
    return faces.has(numeric) ? [] : [`${rule.where}: ${weight} (${isDisplay ? "Fredoka" : "Nunito Sans"})`];
  });
  assert.deepEqual(bad, [], "a weight that is not loaded renders as the nearest one that is");
});

test("capitals come from the one eyebrow recipe", () => {
  const exceptions = new Set([
    // The name-tag sticker's printed "HELLO my name is" band: artwork.
    ".first-run-tag-top",
    // The unit under the restart countdown's number, inside a 10px badge.
    ".restart-approved-countdown span",
    // A status tag in a game's meta line on the profile.
    ".profile-game-outcome",
  ]);
  // Staff screens are read by operators, and keep their own labels.
  const staff = new Set(["operator.css"]);
  const bad = offScale((rule) => {
    if (!rule.declarations.get("text-transform")?.startsWith("uppercase")) return [];
    if (rule.selector === ".section-label" || exceptions.has(rule.selector) || staff.has(rule.file)) return [];
    return [rule.where];
  });
  assert.deepEqual(bad, [], "an eyebrow takes the .section-label class instead of its own capitals");
});
