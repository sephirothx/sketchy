/** The catalogue owns every word, and nothing checks that but this.

TypeScript is happy with a string literal in a component; so is ESLint. The
only thing that notices one left behind is a reader in German looking at an
English button, which is too late. So this reads the tree the way
`backend/tests/test_doc_invariants.py` reads the documents - as source, with a
parser rather than a regex - and fails on a literal in a place a person reads.

The places checked are the ones a person actually reads: text between JSX
tags, the attributes a screen reader speaks, this app's own copy-carrying
props (`label`, `hint`, and the rest), and the arguments of the calls that put
words on screen. A literal anywhere else - a CSS class, a test id, a sort key -
is not copy and is left alone.

Staff surfaces are exempt on purpose (R-I18N-01): the moderation queue and the
operations pages are read by operators in one language.
*/
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";

import { EN } from "../src/content/ui/en.ts";

const ROOT = "src";
const STAFF = [
  "pages/ops/",
  "pages/AdminOperationsPage",
  "pages/ModerationPage",
  "pages/BugReportsPage",
];
// The catalogue itself, and the rules document, hold copy on purpose.
const CONTENT = ["content/"];

// Which argument of each call is the thing a person reads. `notify` takes a
// tone after its message, and `refusalText` takes the message *second* - so
// "the first one" would be wrong in both directions.
const SPEAKING_CALLS = new Map([
  ["notify", 0],
  ["refusalText", 1],
  ["setError", 0],
  ["setNameError", 0],
  ["setPictureError", 0],
  ["setFetchError", 0],
  ["setShareError", 0],
  ["setSubmitError", 0],
  ["setFailure", 0],
  ["setStartError", 0],
  ["setPromotionError", 0],
]);
const SPEAKING_ATTRS = new Set([
  "aria-label", "aria-description", "aria-valuetext", "aria-placeholder",
  "placeholder", "title", "alt", "aria-roledescription",
  // This app's own components take copy as props, and nothing about a prop
  // looks like text - which is exactly why #762's first pass walked past 57
  // of them and a German settings page was still half English (#764).
  "label", "hint", "heading", "caption", "description", "summary",
  "confirmLabel", "cancelLabel", "actionLabel", "emptyLabel", "note",
]);

function sourceFiles(dir = ROOT, out = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) sourceFiles(path, out);
    else if (/\.tsx?$/.test(path)) out.push(path);
  }
  return out;
}

function playerFacing() {
  return sourceFiles().filter((path) => {
    const rel = relative(ROOT, path);
    return ![...STAFF, ...CONTENT].some((prefix) => rel.startsWith(prefix));
  });
}

function literalsIn(path) {
  const text = readFileSync(path, "utf8");
  const source = ts.createSourceFile(
    path, text, ts.ScriptTarget.Latest, true,
    /\.tsx$/.test(path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found = [];
  const at = (node) =>
    `${relative(ROOT, path)}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}`;
  const words = (value) => /[A-Za-z]{2}/.test(value);

  const visit = (node) => {
    if (ts.isJsxText(node) && words(node.text)) {
      found.push(`${at(node)} text ${JSON.stringify(node.text.trim().slice(0, 40))}`);
    } else if (ts.isJsxAttribute(node) && node.initializer) {
      const name = node.name.getText(source);
      const init = node.initializer;
      const inner = ts.isJsxExpression(init) ? init.expression : init;
      if (
        SPEAKING_ATTRS.has(name)
        && inner
        && (ts.isStringLiteral(inner)
          || ts.isTemplateExpression(inner)
          || ts.isNoSubstitutionTemplateLiteral(inner))
        && words(inner.getText(source))
      ) {
        found.push(`${at(node)} ${name}`);
      }
    } else if (ts.isCallExpression(node)) {
      const name = ts.isIdentifier(node.expression)
        ? node.expression.text
        : node.expression.getText(source).split(".").pop();
      const position = SPEAKING_CALLS.get(name);
      const message = position === undefined ? undefined : node.arguments[position];
      if (message) {
        // Anywhere inside the argument, not only at its root: a message is
        // as often `count === 1 ? "..." : "..."` as it is a bare string.
        const inside = (child) => {
          if (
            (ts.isStringLiteral(child)
              || ts.isTemplateExpression(child)
              || ts.isNoSubstitutionTemplateLiteral(child))
            && words(child.getText(source))
          ) {
            found.push(`${at(child)} ${name}()`);
          }
          // A nested speaking call carries its own message and is checked on
          // its own; descending into it would report the same literal twice.
          if (ts.isCallExpression(child)) return;
          ts.forEachChild(child, inside);
        };
        inside(message);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

test("no player-facing screen holds a sentence of its own", () => {
  const offenders = playerFacing().flatMap(literalsIn);
  assert.deepEqual(
    offenders,
    [],
    `these words never reach the catalogue, so they stay English whatever the `
      + `reader chose:\n${offenders.join("\n")}`,
  );
});

test("the scan would notice a literal put back", () => {
  // A test that can only pass is not a test. This proves the parser really is
  // looking at the three places, rather than at a tree it failed to read.
  const cases = [
    ['const x = <p>Hello there</p>;', "text"],
    ['const x = <button aria-label="Close the dialog" />;', "aria-label"],
    ['notify("Saved.");', "notify()"],
  ];
  for (const [snippet, expected] of cases) {
    const source = ts.createSourceFile(
      "probe.tsx", snippet, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX,
    );
    let seen = false;
    const visit = (node) => {
      if (ts.isJsxText(node) && /[A-Za-z]{2}/.test(node.text)) seen ||= expected === "text";
      if (ts.isJsxAttribute(node) && node.name.getText(source) === "aria-label") {
        seen ||= expected === "aria-label";
      }
      if (ts.isCallExpression(node) && node.expression.getText(source) === "notify") {
        seen ||= expected === "notify()";
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
    assert.ok(seen, `the scan cannot see a ${expected} literal`);
  }
});

function* entries(node, path = []) {
  for (const [key, value] of Object.entries(node)) {
    if (typeof value === "object" && value !== null) yield* entries(value, [...path, key]);
    else yield [[...path, key].join("."), value];
  }
}

test("no catalogue entry is blank", () => {
  const blank = [...entries(EN)]
    .filter(([, value]) => typeof value === "string" && value.trim() === "")
    .map(([key]) => key);
  assert.deepEqual(blank, [], `blank entries render as nothing at all: ${blank}`);
});

// Groups nobody names directly, each for a stated reason.
const READ_BY_CODE = {
  refusals: "ui.refusals[errorCode]",
  announcements: "ui.announcements[code]",
  document: "catalogueFor(locale).document, before any component renders",
};

test("every catalogue group is read by something", () => {
  // A group nobody reads is copy that has outlived its screen, and the next
  // translator pays for it in full.
  const sources = playerFacing().map((path) => readFileSync(path, "utf8")).join("\n");
  const unused = Object.keys(EN).filter((group) => !sources.includes(`ui.${group}.`));
  assert.deepEqual(
    unused.sort(),
    Object.keys(READ_BY_CODE).sort(),
    "a group nobody names is either dead copy or reached by code - and if it "
      + "is reached by code, say so in READ_BY_CODE with how.",
  );
});
