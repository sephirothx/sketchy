/** A box that clips its text leaves room for the ink past the text (#1170).

A text box is as wide as its letters' advances, and ink is not confined to
them: a "j" hooks its tail back left of where it starts, and the synthesised
italic a guest's name is drawn in leans past where it ends. Any box that clips
- an ellipsis, a clipped flex item, a scroll container, a text field's inner
editor - cut those pixels off, so "jjf" lost the start of its first letter in
nearly every place a name is shown. Nothing but a reader looking at a name
starting with "j" notices, so this reads the stylesheets for the two shapes:

- A rule that clips text - `text-overflow`, `line-clamp`, or an `overflow`
  that clips on a text-bearing class - carries the allowance as padding and
  gives it back as negative margin (`--ink-overhang` in theme.css):
  `padding-inline: var(--ink-overhang)` and
  `margin-inline: calc(-1 * var(--ink-overhang))`. The start-only forms are
  accepted only for a scroll container (`auto`/`scroll`, no ellipsis or
  clamp), whose wrapped lines never reach its end; anything that truncates or
  clips with `hidden` needs both sides, because the end is where an italic
  leans out.
- A rule that pads a text field indents the text by the allowance
  (`text-indent: var(--ink-overhang)`), and takes it off the start padding so
  the text stays where it was: the field clips at its content box, whatever
  its padding.

A rule that does neither is listed below with the reason it does not need to,
so a new one is looked at before it ships, and an entry nothing matches any
more fails too.

What this cannot see, being a reading of each rule on its own rather than a
cascade: a later or more specific rule that resets `padding` or `margin` on a
box that has the allowance passes here and undoes it there; and a scroll
container, or a clipped wrapper, whose class does not look text-bearing
(`TEXT_BEARING`) is not checked at all. The browser probe that found these
(the PR for #1170) is the check for those. */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const ROOT = "src/styles";

// Class names that hold a player's name or other text somebody typed.
const TEXT_BEARING = /name|author|byline|credit|prompt|chat|crumb/;

const REVIEWED = {
  // Boxes whose text sits inside padding of their own, well over 0.22em.
  "community-lists.css: .community-catalogue-prompt": "a prompt chip, padded 10px either side",
  "community-lists.css: .community-prompts-dialog-body": "the dialog's body, padded 20px",
  "game-room.css: .waiting-custom-prompts-list": "padded 9px, and its virtual rows 9px when it is virtualised",
  "game-room.css: .waiting-custom-prompts-virtual-row span":
    "a prompt chip, padded 7px by `.waiting-custom-prompts-list span`",
  "prompt-lists.css: .prompt-list-entry-editor":
    "a list of prompt chips, each padded 12px at its start by `.prompt-list-entry-editor > li`",
  "lobby-page.css: .public-room-rules > .chip": "a chip of room rules, padded 11px by `.chip`",
  "operator.css: .ops-size-table th[scope=\"row\"]": "a staff table's cell, padded 8px",
  "prompt-stats.css: .prompt-stats-meter": "a bar, with no text",
  // Fields with no text of anybody's to clip.
  "create-room-page.css: .input-number input": "a number, centred in its stepper; digits have no overhang",
  "lobby-page.css: .room-code-field":
    "invisible; the code it takes is drawn in the cells behind it",
  "operator.css: .ops-tunable-control input": "a number, right-aligned; digits have no overhang",
};

const OVERHANG = "var(--ink-overhang)";
const GIVEN_BACK = "calc(-1 * var(--ink-overhang))";

function stylesheets() {
  return readdirSync(ROOT)
    .filter((name) => name.endsWith(".css"))
    .map((name) => ({ name, source: readFileSync(join(ROOT, name), "utf8") }));
}

// Innermost `selector { declarations }` blocks, so a rule inside @media is
// read as itself. Comments are blanked first; braces in strings do not occur
// in these sheets.
function rules({ name, source }) {
  const text = source.replace(/\/\*[\s\S]*?\*\//g, " ");
  const found = [];
  for (const match of text.matchAll(/([^{};]+)\{([^{}]*)\}/g)) {
    const selector = match[1].trim().replace(/\s+/g, " ");
    if (selector.startsWith("@") || /^(from|to|\d+%)/.test(selector)) continue;
    const declarations = new Map();
    for (const part of match[2].split(";")) {
      const colon = part.indexOf(":");
      if (colon < 0) continue;
      declarations.set(
        part.slice(0, colon).trim().toLowerCase(),
        part.slice(colon + 1).replace(/!important/, "").trim(),
      );
    }
    found.push({ file: name, key: `${name}: ${selector}`, selector, declarations });
  }
  return found;
}

function parts(selector) {
  return selector.split(",").map((part) => part.trim());
}

// The compound each comma-separated selector styles: its last one.
function subjects(selector) {
  return parts(selector).map((part) => part.split(/\s*[\s>+~]\s*/).pop());
}

const CLIPS = /\b(hidden|clip|auto|scroll)\b/;

function clipsText({ selector, declarations }) {
  const overflow = declarations.get("text-overflow");
  if (overflow && overflow !== "clip") return true;
  if (declarations.has("-webkit-line-clamp") || declarations.has("line-clamp")) return true;
  // `overflow-y: auto` computes `overflow-x` to auto as well, so it clips
  // sideways too.
  const clips = ["overflow", "overflow-x", "overflow-y"].some((property) =>
    CLIPS.test(declarations.get(property) ?? ""),
  );
  return clips && subjects(selector).some((subject) => TEXT_BEARING.test(subject));
}

// A scroll container: it clips by scrolling (`auto`/`scroll`), never by
// `hidden`/`clip`, and truncates nothing. Its lines wrap, so its end is a
// scrollbar's lane rather than a place a letter is cut.
function isScrollContainer({ declarations }) {
  const overflow = declarations.get("text-overflow");
  if ((overflow && overflow !== "clip") || declarations.has("-webkit-line-clamp") || declarations.has("line-clamp")) {
    return false;
  }
  const values = ["overflow", "overflow-x", "overflow-y"].map((property) => declarations.get(property) ?? "");
  return values.some((value) => /\b(auto|scroll)\b/.test(value)) && !values.some((value) => /\b(hidden|clip)\b/.test(value));
}

function hasInkRoom(rule) {
  const { declarations } = rule;
  const padding = declarations.get("padding-inline") ?? "";
  const margin = declarations.get("margin-inline") ?? "";
  // Both sides: the end is where an italic leans out and an ellipsis box
  // or a clipped item cuts it.
  if (padding === OVERHANG && margin === GIVEN_BACK) return true;
  if (!isScrollContainer(rule)) return false;
  const startPadded =
    padding.startsWith(OVERHANG) || declarations.get("padding-inline-start") === OVERHANG;
  const startGivenBack =
    margin.startsWith(GIVEN_BACK) || declarations.get("margin-inline-start") === GIVEN_BACK;
  return startPadded && startGivenBack;
}

const NOT_TEXT = /\[type="(number|checkbox|radio|range|color|file)"\]/;
// Text fields styled by a class of their own rather than as `input`.
const FIELD_CLASSES = /\.(invite-name-input|room-code-field|room-preset-name|ops-role-search)\b/;

// The text fields a padded rule styles, one `file: selector` per field, since
// a rule that pads a field together with a select or a textarea hands the
// indent to a rule of the field's own (a textarea would indent only its
// first line).
function paddedTextFields({ file, selector, declarations }) {
  const padded = [...declarations.keys()].some((property) => property.startsWith("padding"));
  if (!padded) return [];
  return parts(selector)
    .filter((part) => {
      const subject = subjects(part)[0];
      return (/^input\b/.test(subject) || FIELD_CLASSES.test(subject)) && !NOT_TEXT.test(subject);
    })
    .map((part) => `${file}: ${part}`);
}

// The start (left) side of a `padding` shorthand.
function startOf(shorthand = "") {
  const values = shorthand.split(/\s+/).filter(Boolean);
  return values[values.length === 4 ? 3 : values.length === 1 ? 0 : 1] ?? "";
}

const all = stylesheets().flatMap(rules);

test("every box that clips text leaves room for the ink past it", () => {
  const offenders = all
    .filter((rule) => clipsText(rule) && !hasInkRoom(rule) && !(rule.key in REVIEWED))
    .map((rule) => rule.key);
  assert.deepEqual(offenders, [], "clips text without --ink-overhang");
});

test("every padded text field indents its text by the ink allowance", () => {
  const indented = new Set(
    all
      .filter((rule) => rule.declarations.get("text-indent") === OVERHANG)
      .flatMap((rule) => parts(rule.selector).map((part) => `${rule.file}: ${part}`)),
  );
  // A rule that pads every `input` may hand the indent to one narrowed to its
  // text fields (`input:not([type="checkbox"], ...)`, `input[type="search"]`):
  // an indent on a checkbox means nothing, and on a number it moves the digits.
  const narrowedFrom = (field) =>
    [...indented].some((key) => key.startsWith(`${field}:not(`) || key.startsWith(`${field}[type=`));
  const offenders = [...new Set(all.flatMap(paddedTextFields))].filter(
    (field) => !indented.has(field) && !narrowedFrom(field) && !(field in REVIEWED),
  );
  assert.deepEqual(offenders, [], "pads a text field without text-indent: var(--ink-overhang)");
});

test("a field that indents takes the allowance off its start padding", () => {
  // Otherwise the text moves by the allowance, which is a layout change
  // nobody asked for. A start padding already smaller than the allowance is
  // written as 0 and says so.
  const offenders = all
    .filter((rule) => rule.declarations.get("text-indent") === OVERHANG)
    .filter((rule) => {
      const start = rule.declarations.get("padding-inline-start") ?? startOf(rule.declarations.get("padding"));
      const takenBack = start.includes(`- ${OVERHANG}`) || start === "0";
      const marginBack = rule.declarations.get("margin-inline-start") === GIVEN_BACK;
      return !(takenBack || marginBack);
    })
    .map((rule) => rule.key);
  assert.deepEqual(offenders, [], "indents without taking the allowance back");
});

test("every reviewed exemption is still needed", () => {
  const flagged = new Set([
    ...all.filter((rule) => clipsText(rule) && !hasInkRoom(rule)).map((rule) => rule.key),
    ...all.flatMap(paddedTextFields),
  ]);
  const stale = Object.keys(REVIEWED).filter((key) => !flagged.has(key));
  assert.deepEqual(stale, [], "an exemption for a rule that no longer needs one");
});

test("the allowance is a token, defined once", () => {
  const theme = readFileSync(join(ROOT, "theme.css"), "utf8");
  assert.match(theme, /--ink-overhang:\s*0\.22em;/);
  const definitions = stylesheets().filter(({ source }) => /--ink-overhang\s*:/.test(source));
  assert.deepEqual(definitions.map(({ name }) => name), ["theme.css"]);
});
