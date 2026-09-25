/** The colour pairs hold WCAG AA, in both themes.

Two checks. The first holds the pairs theme.css is built around - body text on
a card, the label on each filled button, a chip's ink on its own wash - to the
bar in both themes. The second reads every stylesheet for a rule that sets a
background and a text colour together and measures that pair, because that is
where the unreadable ones hid: the toast's action wrote --primary-ink on
--primary (1.4:1), and two badges copied it; the restart-vote buttons kept a
white fill under the dark theme's near-white ink (1.05:1); a destructive button
put white on the dark theme's coral --danger (2.8:1); and the update banner's
button wrote a translucent wash on the orange it let through (1.1:1). Most of
them looked fine in the theme they were drawn in.

axe's color-contrast rule stays off in the E2E scans (backend/tests/e2e/
a11y.py), because a player's chosen name colour is not ours to fix; this is
the check for the part that is. It reads the CSS itself - no browser, no
computed styles - so it resolves `var()`, `rgba()` and `color-mix(in srgb)`
by hand, and lays a translucent colour over the ground under it before
measuring, as a browser would. A translucent background is assumed to sit on
--card; the rule-by-rule scan cannot see what an element is nested in.

The bar is WCAG 2.x: 4.5:1 for text (every label here is under 18.66px bold,
so none is "large"), 3:1 for a non-text indicator such as the focus ring. A
rule that cannot meet it yet is listed in KNOWN_SHORT with its reason, and
fails the day it starts passing, so an exemption cannot outlive its problem.
*/
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync } from "node:fs";

const CSS = readFileSync(new URL("../src/styles/theme.css", import.meta.url), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "");

function block(selector) {
  const start = CSS.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `theme.css has no ${selector} block`);
  const body = CSS.slice(CSS.indexOf("{", start) + 1, CSS.indexOf("}", start));
  const tokens = {};
  for (const match of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    tokens[match[1]] = match[2].trim();
  }
  return tokens;
}

const LIGHT = block(":root");
// Dark overrides what it names and inherits the rest, as the cascade does.
const THEMES = {
  light: LIGHT,
  dark: { ...LIGHT, ...block('[data-theme="dark"]') },
};

/** Split on top-level commas only, so a nested call stays one argument. */
function args(inner) {
  const parts = [];
  let depth = 0;
  let current = "";
  for (const char of inner) {
    if (char === "(") depth += 1;
    if (char === ")") depth -= 1;
    if (char === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  parts.push(current.trim());
  return parts;
}

/** A colour as [r, g, b, a], channels 0-255 and alpha 0-1. */
function resolve(value, tokens) {
  const text = value.trim();
  const reference = text.match(/^var\((--[\w-]+)\)$/);
  if (reference) {
    assert.ok(reference[1] in tokens, `${reference[1]} is not declared in theme.css`);
    return resolve(tokens[reference[1]], tokens);
  }
  if (text.startsWith("--")) {
    assert.ok(text in tokens, `${text} is not declared in theme.css`);
    return resolve(tokens[text], tokens);
  }
  const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const digits = hex[1].length === 3 ? [...hex[1]].map((d) => d + d).join("") : hex[1];
    return [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16)).concat(1);
  }
  const rgb = text.match(/^rgba?\(([^)]+)\)$/);
  if (rgb) {
    const [r, g, b, a = "1"] = rgb[1].split(/[\s,/]+/).filter(Boolean);
    const alpha = a.endsWith("%") ? Number(a.slice(0, -1)) / 100 : Number(a);
    return [Number(r), Number(g), Number(b), alpha];
  }
  const mix = text.match(/^color-mix\(in srgb,\s*(.+)\)$/);
  if (mix) {
    const [first, second] = args(mix[1]).map((part) => {
      const weighted = part.match(/^(.+?)\s+([\d.]+)%$/);
      return weighted ? { color: weighted[1], weight: Number(weighted[2]) / 100 } : { color: part };
    });
    const p = first.weight ?? (second.weight === undefined ? 0.5 : 1 - second.weight);
    const a = resolve(first.color, tokens);
    const b = resolve(second.color, tokens);
    return a.map((channel, i) => channel * p + b[i] * (1 - p));
  }
  throw new Error(`a colour this test cannot read: ${text}`);
}

/** Paint `top` over an opaque `ground`, the way a translucent wash renders. */
function over(top, ground) {
  const alpha = top[3];
  return [0, 1, 2].map((i) => top[i] * alpha + ground[i] * (1 - alpha)).concat(1);
}

function luminance([r, g, b]) {
  const linear = (channel) => {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function ratio(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/** The contrast of `fg` on `bg`, `bg` itself laid on `ground` if translucent. */
function contrast(theme, fg, bg, ground = "--card") {
  const tokens = THEMES[theme];
  const base = over(resolve(ground, tokens), [255, 255, 255, 1]);
  const surface = over(resolve(bg, tokens), base);
  return ratio(over(resolve(fg, tokens), surface), surface);
}

const TEXT = 4.5;
const NON_TEXT = 3;

// [foreground, background, what it is]; the background sits on --card unless
// a fourth entry names the ground it is drawn over.
const TEXT_PAIRS = [
  ["--ink", "--paper", "body text on the page"],
  ["--ink", "--card", "body text on a card"],
  ["--ink", "--field", "typed text in a field"],
  ["--muted", "--paper", "secondary text on the page"],
  ["--muted", "--card", "secondary text on a card"],
  ["--on-primary", "--primary", "label on an indigo button, badge or toast action"],
  ["--on-success", "--success-button", "label on a go button, and the approved restart banner"],
  ["--on-danger", "--danger-button", "label on a destructive button, and a kick"],
  ["--primary-ink", "--primary-soft", "indigo chip on a card"],
  ["--primary-ink", "--primary-soft", "indigo chip on the page", "--paper"],
  ["--success-ink", "--success-soft", "success chip"],
  ["--warning", "--warning-soft", "warning chip"],
  ["--danger", "--danger-soft", "danger chip"],
  ["--warm-ink", "--warm-soft", "warm chip"],
  ["--menu-ink", "--menu", "vote-menu text"],
  ["--menu-warning", "--menu", "AFK vote on the menu"],
  ["--menu-danger", "--menu", "kick vote on the menu"],
  ["--menu-warm", "--menu", "report on the menu"],
  ["--menu", "--menu-warning", "a cast AFK vote"],
  ["--menu", "--menu-danger", "a cast kick vote"],
];

const NON_TEXT_PAIRS = [
  ["--focus-ring", "--paper", "focus ring on the page"],
  ["--focus-ring", "--card", "focus ring on a card"],
];

function check(pairs, floor) {
  for (const theme of Object.keys(THEMES)) {
    for (const [fg, bg, what, ground] of pairs) {
      const measured = contrast(theme, fg, bg, ground);
      assert.ok(
        measured >= floor,
        `${what} (${theme}: ${fg} on ${bg}${ground ? ` over ${ground}` : ""}) is ` +
          `${measured.toFixed(2)}:1, under ${floor}:1`,
      );
    }
  }
}

// "file selector theme" -> why that rule is short of 4.5:1 today. Shrinking
// this is the goal; a new entry needs a reason a reviewer would accept.
const FAINT_ICON =
  "--faint colours the magnifier beside the field (non-text), and the field's " +
  "own text sets --ink; the magnifier is under 3:1 in the light theme";
const FAINT_TEXT =
  "a small count written in --faint (2.7:1 light, 3.6:1 dark); needs --muted, not yet changed";
const PRIMARY_TEXT =
  "--primary as text on a dark card is 3.2:1; needs a lighter text indigo, not yet changed";
// Deliberate product decision (2026-09-25): the marker-orange buttons - Quick
// play, Start game, a public room's compact Join - keep white on the brand
// --warm (3.08:1 light, 2.72:1 dark). The orange is the brand's colour for
// "go", and the product owner chose it over a darker fill or dark label.
const BRAND_WARM = "product decision 2026-09-25: brand orange kept, white on --warm";
const KNOWN_SHORT = {
  "primitives.css .btn-warm light": BRAND_WARM,
  "primitives.css .btn-warm dark": BRAND_WARM,
  "community-lists.css .community-prompts-search light": FAINT_ICON,
  "community-lists.css .community-prompts-search dark": FAINT_ICON,
  "lobby-page.css .lobby-room-search light": FAINT_ICON,
  "lobby-page.css .lobby-room-search dark": FAINT_ICON,
  "not-found.css .not-found-tools span light": "decorative tool glyphs on the not-found page",
  "not-found.css .not-found-tools span dark": "decorative tool glyphs on the not-found page",
  "create-room-page.css .prompt-list-chip-count light": FAINT_TEXT,
  "create-room-page.css .prompt-list-chip-count dark": FAINT_TEXT,
  "game-room.css .room-spectator-indicator light": FAINT_TEXT,
  "game-room.css .room-spectator-indicator dark": FAINT_TEXT,
  "create-room-page.css .toggle-chip.is-selected .prompt-list-chip-count dark": PRIMARY_TEXT,
  "game-room.css .wheel-letter-btn dark": PRIMARY_TEXT,
};

const STYLES = new URL("../src/styles/", import.meta.url);
const COLOUR = String.raw`(var\(--[\w-]+\)|#[0-9a-f]{3}(?:[0-9a-f]{3})?)\s*(?:!important)?\s*;`;
// A ring and the surface it re-points for are read whatever they are written
// as: resolve() understands var(), hex, rgb()/rgba() and color-mix(), and
// throws on anything else, so a value this cannot measure fails the test
// rather than being skipped. The text scan stays with var() and hex: which
// ground a literal translucent wash lands on is not in the rule.
const ANY_COLOUR = String.raw`([^;]+?)\s*(?:!important)?\s*;`;
const RING = new RegExp(String.raw`(?:^|[;\s])--focus-ring\s*:\s*` + ANY_COLOUR, "i");
const BACKGROUND = new RegExp(String.raw`(?:^|[;\s])background(?:-color)?\s*:\s*` + COLOUR, "i");
const ANY_BACKGROUND = new RegExp(
  String.raw`(?:^|[;\s])background(?:-color)?\s*:\s*` + ANY_COLOUR,
  "i",
);
const FOREGROUND = new RegExp(String.raw`(?:^|[;\s])color\s*:\s*` + COLOUR, "i");

/** Every rule in every stylesheet that sets `foreground` (a text colour, or a
    re-pointed focus ring), with the background it sets beside it, if any. */
function paintedRules(foreground = FOREGROUND, background = BACKGROUND) {
  const rules = [];
  // theme.css declares the defaults, which the pair tables above measure.
  const sheets = readdirSync(STYLES).filter((name) => name.endsWith(".css") && name !== "theme.css");
  for (const file of sheets) {
    const css = readFileSync(new URL(file, STYLES), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const [, selector, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const bg = body.match(background);
      const fg = body.match(foreground);
      if (!fg) continue;
      const token = (value) => (value.startsWith("var(") ? value.slice(4, -1) : value);
      rules.push({
        name: `${file} ${selector.trim().replace(/\s+/g, " ")}`,
        fg: token(fg[1]),
        bg: bg ? token(bg[1]) : null,
      });
    }
  }
  return rules;
}

test("the contrast arithmetic is WCAG's", () => {
  assert.equal(ratio([0, 0, 0], [255, 255, 255]).toFixed(1), "21.0");
  assert.equal(ratio([118, 118, 118], [255, 255, 255]).toFixed(2), "4.54");
  // A wash is measured where it lands: 50% black over white is mid-grey.
  const grey = over([0, 0, 0, 0.5], [255, 255, 255, 1]);
  assert.deepEqual(grey.map(Math.round), [128, 128, 128, 1]);
});

test("text tokens reach 4.5:1 on the grounds they are written on, in both themes", () => {
  check(TEXT_PAIRS, TEXT);
});

test("the focus ring reaches 3:1 against the page and a card, in both themes", () => {
  check(NON_TEXT_PAIRS, NON_TEXT);
});

test("a rule that paints a background and writes on it reaches 4.5:1, in both themes", () => {
  const rules = paintedRules().filter((rule) => rule.bg);
  // The scan is only worth something if it finds the rules it is about.
  assert.ok(rules.some((rule) => rule.name === "global-feedback.css .app-toast .app-toast-action"));
  const seen = new Set();
  for (const rule of rules) {
    for (const theme of Object.keys(THEMES)) {
      const key = `${rule.name} ${theme}`;
      seen.add(key);
      const measured = contrast(theme, rule.fg, rule.bg);
      if (key in KNOWN_SHORT) {
        assert.ok(
          measured < TEXT,
          `${key} now reaches ${measured.toFixed(2)}:1 - drop it from KNOWN_SHORT`,
        );
        continue;
      }
      assert.ok(
        measured >= TEXT,
        `${key}: ${rule.fg} on ${rule.bg} is ${measured.toFixed(2)}:1, under ${TEXT}:1`,
      );
    }
  }
  for (const key of Object.keys(KNOWN_SHORT)) {
    assert.ok(seen.has(key), `KNOWN_SHORT names ${key}, which is no longer a painted rule`);
  }
});

test("a surface that re-points the focus ring keeps it at 3:1 on that surface, in both themes", () => {
  // The global ring is checked against the page and a card above; a surface
  // that is neither - the dark vote menus, the reaction strip, the white name
  // tag - sets its own --focus-ring, and must say on the same rule what it
  // paints, so the pair can be measured here.
  const rules = paintedRules(RING, ANY_BACKGROUND);
  assert.ok(rules.some((rule) => rule.name === "reactions.css .reaction-picker"));
  for (const rule of rules) {
    assert.ok(rule.bg, `${rule.name} re-points --focus-ring without naming its background`);
    for (const theme of Object.keys(THEMES)) {
      const measured = contrast(theme, rule.fg, rule.bg);
      assert.ok(
        measured >= NON_TEXT,
        `${rule.name} ${theme}: ring ${rule.fg} on ${rule.bg} is ${measured.toFixed(2)}:1`,
      );
    }
  }
});
