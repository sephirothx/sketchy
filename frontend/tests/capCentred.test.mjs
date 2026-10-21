/** A label centred in a shape is centred on its capitals and digits
(`.cap-centred`, primitives.css says why and where it may go).

This holds the primitive to its declaration and keeps it the only rule that
trims a text box: a `text-box` rule anywhere else - another selector in
primitives.css, a descendant of the class, a second `.cap-centred` in a
surface sheet - would be a fix for one shape the next shape does not get.
And it holds Solo's numbers in shapes to the class: the calendar's dates,
the Daily's ring numbers and the free-run glyphs. */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const ROOT = "src/styles";
const PRIMITIVES = join(ROOT, "primitives.css");

function stylesheets(dir = ROOT) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return stylesheets(path);
    return entry.name.endsWith(".css") ? [path] : [];
  });
}

function rules(path) {
  const css = readFileSync(path, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  return [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)].map((match) => ({
    selector: match[1].trim(),
    body: match[2],
  }));
}

test("the cap-centred primitive trims to cap height and baseline", () => {
  const [rule, ...more] = rules(PRIMITIVES).filter((each) => each.selector === ".cap-centred");
  assert.ok(rule, "primitives.css defines .cap-centred");
  assert.deepEqual(more, [], "once");
  assert.match(rule.body, /text-box:\s*trim-both cap alphabetic;/);
});

test("only the primitive trims text boxes", () => {
  const elsewhere = stylesheets().flatMap((path) =>
    rules(path)
      .filter((each) => /\btext-box(?:-trim|-edge)?\s*:/.test(each.body))
      .filter((each) => !(path === PRIMITIVES && each.selector === ".cap-centred"))
      .map((each) => `${path}: ${each.selector}`),
  );
  assert.deepEqual(elsewhere, [], "use .cap-centred rather than a text-box rule of its own");
});

test("Solo's numbers in shapes use it, on the label rather than the shape", () => {
  const page = readFileSync("src/pages/SoloPage.tsx", "utf8");
  const dates = page.match(/<span className="solo-calendar-date[^"]*">/g) ?? [];
  assert.ok(dates.length > 0, "the calendar draws its dates");
  for (const date of dates) assert.match(date, /\bcap-centred\b/, "every calendar date");
  assert.match(page, /<span className="cap-centred" aria-hidden="true">\{index \+ 1\}<\/span>/, "the Daily's ring numbers");
  assert.match(page, /<span className="cap-centred">\{length === null \? "∞" : length\}<\/span>/, "the free-run glyphs");
  assert.doesNotMatch(page, /className="[^"]*\bsolo-(ring|run-glyph|calendar-day)\b[^"]*\bcap-centred\b/, "never on the shape");
});
