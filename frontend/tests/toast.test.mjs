import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";

import { MAX_TOASTS, keepRecentToasts, sameToast } from "../src/lib/toast.ts";

const stack = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }));
// The stack rules on their own: no toast repeats another.
const never = () => false;

test("a toast arriving on an empty screen stands alone", () => {
  const { kept, evicted } = keepRecentToasts([], { id: 9 }, never);
  assert.deepEqual(kept, [{ id: 9 }]);
  assert.deepEqual(evicted, []);
});

test("the stack fills to the cap without dropping anything", () => {
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS - 1), { id: 99 }, never);
  assert.equal(kept.length, MAX_TOASTS);
  assert.deepEqual(evicted, []);
});

test("past the cap the oldest falls off, newest last", () => {
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS), { id: 99 }, never);
  assert.equal(kept.length, MAX_TOASTS);
  assert.deepEqual(evicted, [{ id: 1 }]);
  assert.deepEqual(kept.at(-1), { id: 99 });
});

test("whatever falls off is handed back, so its timer can be cleared", () => {
  // A dropped toast whose timer still runs leaves an entry behind and fires a
  // dismissal for something nobody can see.
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS + 3), { id: 99 }, never);
  assert.equal(kept.length, MAX_TOASTS);
  assert.equal(evicted.length, 4);
  assert.deepEqual(
    evicted.map((toast) => toast.id),
    [1, 2, 3, 4],
  );
});

test("a toast arriving on a screen below the cap evicts nothing", () => {
  const { kept, evicted } = keepRecentToasts(stack(1), { id: 42 }, never);
  assert.deepEqual(evicted, []);
  assert.ok(kept.some((toast) => toast.id === 42));
});

test("a toast saying what one on screen says replaces it rather than stacking", () => {
  const same = (a, b) => a.message === b.message;
  const current = [{ id: 1, message: "other" }, { id: 2, message: "too short" }];
  const { kept, evicted } = keepRecentToasts(current, { id: 3, message: "too short" }, same);
  assert.deepEqual(kept.map((t) => t.id), [1, 3]);
  assert.deepEqual(evicted.map((t) => t.id), [2]);
  // Without the rule, nothing is treated as a repeat.
  assert.equal(keepRecentToasts(current, { id: 3, message: "too short" }, never).kept.length, 3);
});

test("a repeat is the same words in the same tone, with nothing to act on", () => {
  const refusal = { message: "Too short", tone: "error" };
  assert.equal(sameToast(refusal, { message: "Too short", tone: "error" }), true);
  assert.equal(sameToast(refusal, { message: "Too long", tone: "error" }), false);
  // The same words as a warning are something else to say.
  assert.equal(sameToast(refusal, { message: "Too short", tone: "warning" }), false);
  // An action is its own offer, on either side.
  const offer = { message: "Too short", tone: "error", action: { label: "Fix", onClick() {} } };
  assert.equal(sameToast(refusal, offer), false);
  assert.equal(sameToast(offer, refusal), false);
  assert.equal(sameToast(offer, offer), false);
});

// A failure sent with any tone but "error" renders as a blue info (or green,
// or amber) toast with role="status": it looks like news rather than a
// problem, and a screen reader waits its turn to say it. Eight friend and
// invitation failures went out that way before anything checked.
//
// The compiler now insists on a tone at every call (`ToastContextValue`), so
// this is left with the other half: a tone that is there but wrong. It reads
// every `notify(...)` in the source and fails on one whose message is plainly
// a failure - a refusal sentence, a socket error, a caught error, or a
// key or literal that says it could not, cannot, failed, went wrong or was refused -
// sent with a tone that cannot be "error". A message held in a `const` in the
// same file is followed to what it was set to. A conditional tone is read
// branch by branch: when the message branches on the same condition, each
// message branch is held to its own tone; otherwise every branch the failure
// can reach has to be "error".
const ROOT = "src";
const FAILURE_CALLS = new Set(["refusalText", "refusalSentence", "socketRequestErrorMessage"]);
const FAILURE_KEY = /could\s?n[o']?t|cannot|failed|went\s?wrong|refused/i;
// What a `catch` names what it caught, in this source.
const CAUGHT = /^(err|error|failure|problem|caught|\w+Error)$/;

function sourceFiles(dir = ROOT, out = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) sourceFiles(path, out);
    else if (/\.tsx?$/.test(path)) out.push(path);
  }
  return out;
}

const unwrap = (node) => (node && ts.isParenthesizedExpression(node) ? unwrap(node.expression) : node);

function misTonedFailures(path, text = readFileSync(path, "utf8")) {
  const source = ts.createSourceFile(
    path, text, ts.ScriptTarget.Latest, true,
    /\.tsx$/.test(path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  // Every `const name = ...` in the file, by name. A name declared twice in
  // two scopes counts as a failure if either one is: a false alarm here is a
  // rename, a missed one is a red toast drawn blue.
  const consts = new Map();
  const collect = (node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer
      && ts.isVariableDeclarationList(node.parent)
      && (node.parent.flags & ts.NodeFlags.Const)) {
      consts.set(node.name.text, [...(consts.get(node.name.text) ?? []), node.initializer]);
    }
    ts.forEachChild(node, collect);
  };
  collect(source);

  const saysFailure = (node, following = new Set()) => {
    let failure = false;
    const visit = (child) => {
      if (failure) return;
      if (ts.isCallExpression(child) && ts.isIdentifier(child.expression)
        && FAILURE_CALLS.has(child.expression.text)) {
        failure = true;
      } else if (ts.isIdentifier(child)) {
        const name = child.text;
        if (FAILURE_KEY.test(name) || CAUGHT.test(name)) failure = true;
        else if (consts.has(name) && !following.has(name)) {
          const next = new Set(following).add(name);
          failure = consts.get(name).some((init) => saysFailure(init, next));
        }
      } else if ((ts.isStringLiteralLike(child) || ts.isTemplateLiteralToken(child))
        && FAILURE_KEY.test(child.text)) {
        failure = true;
      } else {
        ts.forEachChild(child, visit);
      }
    };
    visit(node);
    return failure;
  };

  // Whether a failure in `message` can be drawn in a tone other than "error".
  const misToned = (messageNode, toneNode) => {
    const message = unwrap(messageNode);
    const tone = unwrap(toneNode);
    if (tone && ts.isConditionalExpression(tone)) {
      const sameCondition = ts.isConditionalExpression(message)
        && unwrap(message.condition).getText(source) === unwrap(tone.condition).getText(source);
      return sameCondition
        ? misToned(message.whenTrue, tone.whenTrue) || misToned(message.whenFalse, tone.whenFalse)
        : misToned(message, tone.whenTrue) || misToned(message, tone.whenFalse);
    }
    if (!saysFailure(message)) return false;
    return !(tone && ts.isStringLiteralLike(tone) && tone.text === "error");
  };

  const found = [];
  const visit = (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)
      && node.expression.text === "notify" && node.arguments.length > 0) {
      const [message, tone] = node.arguments;
      if (misToned(message, tone)) {
        const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
        found.push(`${relative(ROOT, path)}:${line}`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

test("the scan catches a failure toast sent with a tone that is not error", () => {
  const snippet = `
    notify(refusalText(answer, ui.playerList.requestCouldNotBeSent), "info");
    notify(ui.playerList.thatRequestCouldNotBeSent, "success");
    notify(ui.playerList.thatRequestCouldNotBeSent, "error");
    notify(ui.playerList.friendRequestSent({ name }), "success");
    const message = refusalText(response, ui.roomSettingsEditor.roomRefusedThoseSettings);
    notify(message, "info");
    notify(ui.lobbyPage.failedCreateRoom, "warning");
    notify(ui.lobbyPage.somethingWentWrongPleaseTryAgain, "info");
    notify(String(err), "info");
    notify(ui.x["couldNotY"], "info");
    notify(ok ? ui.x.saved : ui.x.couldNotSave, ok ? "success" : "error");
    notify(ok ? ui.x.saved : ui.x.couldNotSave, ok ? "success" : "info");
    notify("Could not copy the report.", "success");
    notify(\`Couldn't reach \${what}.\`, "info");
    notify(ui.x.cannotJoin, "info");
    notify("Report copied as Markdown.", "success");
    notify(ui.x.couldNotSave, ok ? "error" : "success");
    notify(ok ? ui.x.couldNotSave : ui.x.saved, ok ? "success" : "error");
    notify(!ok ? ui.x.couldNotSave : ui.x.saved, !ok ? "error" : "success");
  `;
  assert.deepEqual(misTonedFailures("src/snippet.ts", snippet), [
    "snippet.ts:2",
    "snippet.ts:3",
    "snippet.ts:7",
    "snippet.ts:8",
    "snippet.ts:9",
    "snippet.ts:10",
    "snippet.ts:11",
    "snippet.ts:13",
    "snippet.ts:14",
    "snippet.ts:15",
    "snippet.ts:16",
    "snippet.ts:18",
    "snippet.ts:19",
  ]);
});

test("every failure toast carries the error tone", () => {
  assert.deepEqual(sourceFiles().flatMap((path) => misTonedFailures(path)), []);
});
