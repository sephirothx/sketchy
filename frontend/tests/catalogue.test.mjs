/** The catalogue owns every word, and nothing checks that but this.

TypeScript is happy with a string literal in a component; so is ESLint. The
only thing that notices one left behind is a reader in German looking at an
English button, which is too late. So this reads the tree the way
`backend/tests/test_doc_invariants.py` reads the documents - as source, with a
parser rather than a regex - and fails on a literal in a place a person reads.

The places checked are the ones a person actually reads: text between JSX
tags, the attributes a screen reader speaks, this app's own copy-carrying
props (`label`, `hint`, and the rest), and the arguments of the calls that put
words on screen. A second scan reads where words hide out of the markup: the
tables of labels, the branches, fallbacks and returned sentences. A literal
that is plumbing - a CSS class, a test id, a sort key - is left alone, and one
that only looks like words says so with a `// Not copy:` comment.

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
  ["setNotice", 0],
  ["setReportNotice", 0],
  ["setRosterError", 0],
  ["setDeliveryError", 0],
  ["setDetailError", 0],
  ["setAnnouncement", 0],
  ["setDone", 0],
  ["confirm", 0],
  ["failed", 0],
  // The verb phrase slotted into "Could not …" - words, even when lowercase.
  ["socketRequestErrorMessage", 1],
  ["requestErrorMessage", 1],
]);
const SPEAKING_ATTRS = new Set([
  "aria-label", "aria-description", "aria-valuetext", "aria-placeholder",
  "placeholder", "title", "alt", "aria-roledescription",
  // This app's own components take copy as props, and nothing about a prop
  // looks like text - which is exactly why #762's first pass walked past 57
  // of them and a German settings page was still half English (#764).
  "label", "hint", "heading", "caption", "description", "summary",
  "confirmLabel", "cancelLabel", "actionLabel", "emptyLabel", "note",
  "backLabel", "closeLabel", "namePlaceholder", "data-label",
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

function literalsIn(path, text = readFileSync(path, "utf8")) {
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
        // A value compared against (`action === "accept" ? … : …`) picks the
        // message; it is not part of it.
        const compared = (child) => ts.isBinaryExpression(child.parent)
          && [ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken]
            .includes(child.parent.operatorToken.kind);
        const inside = (child) => {
          if (
            (ts.isStringLiteral(child)
              || ts.isTemplateExpression(child)
              || ts.isNoSubstitutionTemplateLiteral(child))
            && words(child.getText(source))
            && !compared(child)
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
  const offenders = playerFacing().flatMap((path) => literalsIn(path));
  assert.deepEqual(
    offenders,
    [],
    `these words never reach the catalogue, so they stay English whatever the `
      + `reader chose:\n${offenders.join("\n")}`,
  );
});

test("the scan would notice a literal put back", () => {
  // A test that can only pass is not a test. The snippets go through the scan
  // itself, parsed as if they were a source file, so this proves the scan and
  // not a copy of it.
  const probe = (snippet) => literalsIn(join(ROOT, "__probe__.tsx"), snippet).length > 0;
  for (const snippet of [
    "const x = <p>Hello there</p>;",
    'const x = <button aria-label="Close the dialog" />;',
    'const x = <AppHeader backLabel="Back to lobby" />;',
    "const x = <AppHeader backLabel={`Back to ${place}`} />;",
    'notify("Saved.");',
    'setError(action === "accept" ? "Could not accept." : "Could not dismiss.");',
  ]) {
    assert.ok(probe(snippet), `the scan cannot see: ${snippet}`);
  }
  assert.ok(!probe('notify(action === "accept" ? ui.a.b : ui.a.c);'),
    "a value compared against picks the message; it is not part of it");
});

// Where a sentence hides once it is out of the markup: a table of labels, a
// branch that picks one of two, a fallback, a function that returns one. The
// first scan walked past every one of these, and #764's "complete" German
// still had a settings tab bar, the report reasons and half the waiting room
// in English. So this reads those places too, and a literal found there is copy
// unless it says otherwise: a `// Not copy: <why>` comment above it, a key or
// attribute that is plumbing by name, or a call that is styling or a log.
const NOT_COPY_NAMES = new Set([
  "id", "key", "className", "type", "kind", "testId", "href", "path", "icon", "color",
  "event", "code", "slug", "variant", "role", "tone", "mode", "errorCode", "method", "storageKey",
  "format", "hourCycle", "locale", "language", "transform", "rootMargin", "boxShadow",
  "transition", "fontFamily", "background", "gridTemplateColumns", "style", "data-testid", "src",
  "target", "rel", "autoComplete", "inputMode", "pattern", "accept", "form", "htmlFor",
  "download", "stroke", "fill", "d", "viewBox", "width", "height", "track", "name",
]);
const NOT_COPY_CALLS = new Set([
  "log", "warn", "error", "info", "debug", "recordClientError", "redactDiagnostic",
  "useMediaQuery", "matchMedia", "mediaQuery", "Error", "SocketRequestError", "ApiError",
  "cx", "clsx", "includes", "indexOf", "has", "startsWith", "endsWith", "querySelector",
  "setAttribute", "setItem", "getItem",
]);
// What goes into a crash report or an error log is read by an operator.
const DIAGNOSTIC = ["lib/crashReport", "lib/clientErrorLog"];
// Staff modules; the one player-facing word in lib/moderation (a category a
// player was warned for) comes from the catalogue.
const STAFF_LIBS = ["lib/operations", "lib/adminControls", "lib/moderation"];
const BRAND = new Set(["Sketchy"]);
const LOOKUPS = new Set(["includes", "indexOf", "lastIndexOf", "some", "every", "find", "findIndex"]);

function looksLikeASentence(node) {
  const parts = ts.isTemplateExpression(node)
    ? [node.head.text, ...node.templateSpans.map((span) => span.literal.text)]
    : [node.text];
  const text = parts.join("");
  if (BRAND.has(text.trim()) || !/[A-Za-z]{2}/.test(text)) return false;
  // A template's words need not sit beside each other: in `${n} players` or
  // `${label} scoring` no part holds two words, and #762 closed with both
  // still English. A literal part holding one whole word is copy - unless the
  // template is CSS (`translate(${x}px, …)`, a bare unit) or glued plumbing
  // (`chip-${kind}`, `/api/${id}`, `${name}.png`), which never stands a word
  // alone between spaces. Asked first: trimmed, ` players` is one lowercase
  // token, which the checks below would take for a class name.
  if (ts.isTemplateExpression(node)) {
    if (parts.some((part) => /\w\(/.test(part))) return false;
    const UNITS = /^(px|em|rem|ms|vh|vw|fr|deg)\b/;
    if (parts.some((part) =>
      /(^|[\s:;,!?(·—–])[A-Za-z]{2,}(?=[\s:;,.!?)·—–]|$)/.test(part) && !UNITS.test(part.trim()))) {
      return true;
    }
  }
  if (/^(https?:|\/|#|--|var\(|\.|\[)/.test(text) || /[{};]\s*$/.test(text)) return false;
  if (/^[a-z-]+\s*:/.test(text) || /^[a-z0-9_.\/:-]*$/.test(text.trim())) return false;
  // A class list - "chip is-active" - rather than lowercase words like "cut short".
  const tokens = text.trim().split(/\s+/);
  if (tokens.every((t) => /^[a-z][a-z0-9-]*$/.test(t)) && tokens.some((t) => t.includes("-"))) return false;
  return /[A-Za-z][^\s]*\s+\S/.test(text) || /^\s*[A-Z][a-z]/.test(text);
}

function tableLiteralsIn(path, text = readFileSync(path, "utf8")) {
  const source = ts.createSourceFile(
    path, text, ts.ScriptTarget.Latest, true,
    /\.tsx$/.test(path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found = [];
  const callee = (call) => call.expression.getText(source).split(".").pop();
  const marked = (node) => {
    for (let at = node; at && !ts.isSourceFile(at); at = at.parent) {
      const comments = ts.getLeadingCommentRanges(text, at.getFullStart()) ?? [];
      if (comments.some((c) => /not copy:/i.test(text.slice(c.pos, c.end)))) return true;
    }
    return false;
  };
  const excused = (node) => {
    for (let at = node.parent; at && !ts.isSourceFile(at); at = at.parent) {
      if (ts.isJsxAttribute(at) && NOT_COPY_NAMES.has(at.name.getText(source))) return true;
      if (ts.isPropertyAssignment(at) && NOT_COPY_NAMES.has(at.name.getText(source).replace(/["']/g, ""))) return true;
      if ((ts.isCallExpression(at) || ts.isNewExpression(at)) && NOT_COPY_CALLS.has(callee(at))) return true;
      // A list something is looked up in, rather than shown: `[...].includes(key)`.
      // Only a lookup - `[...].join(" · ")` is a list being shown.
      if (ts.isPropertyAccessExpression(at) && ts.isArrayLiteralExpression(at.expression)
        && LOOKUPS.has(at.name.text)) return true;
    }
    return marked(node);
  };
  const place = (node) => {
    let child = node;
    let parent = node.parent;
    while (ts.isParenthesizedExpression(parent) || ts.isAsExpression(parent) || ts.isSatisfiesExpression(parent)) {
      child = parent;
      parent = parent.parent;
    }
    if (ts.isPropertyAssignment(parent) && parent.initializer === child) return "table";
    if (ts.isArrayLiteralExpression(parent)) return "list";
    // `parts.push(`${n} custom`)`, then `parts.join(" · ")`: a list built a
    // piece at a time is a list all the same.
    if (ts.isCallExpression(parent) && parent.arguments.includes(child)
      && ["push", "unshift", "concat"].includes(parent.expression.getText(source).split(".").pop())) return "list";
    if (ts.isReturnStatement(parent) || (ts.isArrowFunction(parent) && parent.body === child)) return "return";
    if (ts.isVariableDeclaration(parent) && parent.initializer === child) return "constant";
    if (ts.isConditionalExpression(parent) && parent.condition !== child) return "branch";
    if (ts.isBinaryExpression(parent)) {
      const op = parent.operatorToken.kind;
      if ((op === ts.SyntaxKind.BarBarToken || op === ts.SyntaxKind.QuestionQuestionToken) && parent.right === child) return "fallback";
      if (op === ts.SyntaxKind.PlusToken) return "concatenation";
      // `{signedOut && "You signed out everywhere."}` renders the right side.
      if (op === ts.SyntaxKind.AmpersandAmpersandToken && parent.right === child) return "condition";
    }
    if (ts.isJsxExpression(parent) && !ts.isJsxAttribute(parent.parent)) return "jsx";
    const attr = ts.isJsxAttribute(parent) ? parent : ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent) ? parent.parent : null;
    if (attr && !SPEAKING_ATTRS.has(attr.name.getText(source))) return "prop";
    return null;
  };
  // `n === 1 ? "round" : "rounds"` - a plural English happens to need, and no
  // other language's. Counts go through `counted`/`plural` in the catalogue.
  const countOfOne = (condition) => ts.isBinaryExpression(condition)
    && [ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken,
      ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken,
      ts.SyntaxKind.GreaterThanToken].includes(condition.operatorToken.kind)
    && [condition.left, condition.right].some((side) => ts.isNumericLiteral(side) && side.text === "1");
  const wordOrNothing = (branch) => (ts.isStringLiteral(branch) || ts.isNoSubstitutionTemplateLiteral(branch))
    && /^[\p{L} ]*$/u.test(branch.text);
  const visit = (node) => {
    if (ts.isConditionalExpression(node) && countOfOne(node.condition)
      && wordOrNothing(node.whenTrue) && wordOrNothing(node.whenFalse)
      && (node.whenTrue.text.trim() || node.whenFalse.text.trim()) && !excused(node.whenTrue)) {
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
      found.push(`${relative(ROOT, path)}:${line} plural ${node.getText(source).slice(0, 50)}`);
    }
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateExpression(node))
      && looksLikeASentence(node)) {
      const where = place(node);
      if (where && !excused(node)) {
        const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
        found.push(`${relative(ROOT, path)}:${line} ${where} ${node.getText(source).slice(0, 50)}`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

test("no table, branch or fallback holds a sentence of its own", () => {
  const offenders = playerFacing()
    .filter((path) => ![...DIAGNOSTIC, ...STAFF_LIBS].some((prefix) => relative(ROOT, path).startsWith(prefix)))
    .flatMap((path) => tableLiteralsIn(path));
  assert.deepEqual(
    offenders,
    [],
    `these read as words but sit outside the catalogue - move them to it, or `
      + `mark a genuine exception with \`// Not copy: <why>\`:\n${offenders.join("\n")}`,
  );
});

test("the table scan would notice a sentence put back", () => {
  // Parsed as if it were a source file, without writing one.
  const probe = (snippet) => tableLiteralsIn(join(ROOT, "__probe__.tsx"), snippet).length > 0;
  for (const snippet of [
    'const LABELS = { spam: "Spam or scams" };',
    'const x = busy ? "Saving…" : "Save";',
    'const y = name || "A player";',
    'function f() { return "Not in a room"; }',
    "const z = `${count} custom prompts`;",
    // Inside JSX and inside a speaking attribute, where WarningNotice and
    // SuspensionNotice kept theirs.
    'const el = <p>{several ? "The messages this was about:" : "The message this was about:"}</p>;',
    'const el = <p>{signedOut && "You signed out everywhere."}</p>;',
    'const el = <button aria-label={open ? "Close the menu" : "Open the menu"} />;',
    'const el = <Header title={name || "A player"} />;',
    // The three shapes #762 was reopened for.
    'const s = total ? `${total} ${total === 1 ? "reaction" : "reactions"}: ${chips}` : none;',
    "const footer = [`${maxPlayers} players`, `${drawingSeconds}s`].join(\" · \");",
    "const scoring = `${scoringLabelFor(mode)} scoring`;",
    'const rounds = count === 1 ? "round" : "rounds";',
    // The three #786's review found.
    "parts.push(`${customPrompts.analysis.usableCount} custom`);",
    "const el = <span title={isAnonymous ? `${nickname} (guest)` : undefined} />;",
    "const highlight = { label: ui.x.y, value: `${correct} of ${total} guessed it` };",
  ]) {
    assert.ok(probe(snippet), `the table scan cannot see: ${snippet}`);
  }
  for (const plumbing of [
    'const c = active ? "chip is-active" : "chip";',
    'const u = "/api/rooms";',
    'const s = "Sketchy";',
    'const el = <div className={on ? "panel is-open" : "panel"} />;',
    'if (["Control", "Shift"].includes(key)) skip();',
    "const t = active ? `translate(${x}px, ${y}px)` : undefined;",
    "const f = [`sketchy-${date}.png`, `chip-${kind}`, `/api/rooms/${id}`, `${seconds}s`];",
    'const size = place === 1 ? 52 : 42;',
    'const color = rank === 1 ? "var(--gold)" : null;',
    '// Not copy: a filename.\nconst f = "Sketchy recovery codes.txt";',
  ]) {
    assert.ok(!probe(plumbing), `the table scan takes plumbing for words: ${plumbing}`);
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
  moderationCategories: "humanizeCategory(), by the category a moderator recorded",
  promptTags: "tagName() in MyPromptListsPage, by the slug the server sent",
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
