import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";

import { MAX_TOASTS, keepRecentToasts } from "../src/lib/toast.ts";

const stack = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }));

test("a toast arriving on an empty screen stands alone", () => {
  const { kept, evicted } = keepRecentToasts([], { id: 9 });
  assert.deepEqual(kept, [{ id: 9 }]);
  assert.deepEqual(evicted, []);
});

test("the stack fills to the cap without dropping anything", () => {
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS - 1), { id: 99 });
  assert.equal(kept.length, MAX_TOASTS);
  assert.deepEqual(evicted, []);
});

test("past the cap the oldest falls off, newest last", () => {
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS), { id: 99 });
  assert.equal(kept.length, MAX_TOASTS);
  assert.deepEqual(evicted, [{ id: 1 }]);
  assert.deepEqual(kept.at(-1), { id: 99 });
});

test("whatever falls off is handed back, so its timer can be cleared", () => {
  // A dropped toast whose timer still runs leaves an entry behind and fires a
  // dismissal for something nobody can see.
  const { kept, evicted } = keepRecentToasts(stack(MAX_TOASTS + 3), { id: 99 });
  assert.equal(kept.length, MAX_TOASTS);
  assert.equal(evicted.length, 4);
  assert.deepEqual(
    evicted.map((toast) => toast.id),
    [1, 2, 3, 4],
  );
});

test("a toast arriving on a screen below the cap evicts nothing", () => {
  const { kept, evicted } = keepRecentToasts(stack(1), { id: 42 });
  assert.deepEqual(evicted, []);
  assert.ok(kept.some((toast) => toast.id === 42));
});

// A failure sent without the error tone renders as a blue info toast with
// role="status": it looks like news rather than a problem, and a screen reader
// waits its turn to say it. Four friend and invitation failures went out that
// way before anything checked, so this reads every `notify(...)` in the source
// and fails on one whose message is plainly a failure - a refusal sentence, a
// socket error, or a catalogue key that says "could not" - without "error".
const ROOT = "src";
const FAILURE_CALLS = new Set(["refusalText", "refusalSentence", "socketRequestErrorMessage"]);
const FAILURE_KEY = /couldn(ot|t)/i;

function sourceFiles(dir = ROOT, out = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) sourceFiles(path, out);
    else if (/\.tsx?$/.test(path)) out.push(path);
  }
  return out;
}

function untonedFailures(path, text = readFileSync(path, "utf8")) {
  const source = ts.createSourceFile(
    path, text, ts.ScriptTarget.Latest, true,
    /\.tsx$/.test(path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found = [];
  const saysFailure = (node) => {
    let failure = false;
    const visit = (child) => {
      if (failure) return;
      if (ts.isCallExpression(child) && ts.isIdentifier(child.expression)
        && FAILURE_CALLS.has(child.expression.text)) failure = true;
      else if (ts.isIdentifier(child) && FAILURE_KEY.test(child.text)) failure = true;
      else ts.forEachChild(child, visit);
    };
    visit(node);
    return failure;
  };
  const visit = (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)
      && node.expression.text === "notify" && node.arguments.length > 0) {
      const [message, tone] = node.arguments;
      const toned = tone && ts.isStringLiteral(tone) && tone.text === "error";
      if (saysFailure(message) && !toned) {
        const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
        found.push(`${relative(ROOT, path)}:${line}`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

test("the scan catches a failure toast sent without the error tone", () => {
  const snippet = `
    notify(refusalText(answer, ui.playerList.requestCouldNotBeSent));
    notify(ui.playerList.thatRequestCouldNotBeSent, "info");
    notify(ui.playerList.thatRequestCouldNotBeSent, "error");
    notify(ui.playerList.friendRequestSent({ name }));
  `;
  assert.deepEqual(untonedFailures("src/snippet.ts", snippet), [
    "snippet.ts:2",
    "snippet.ts:3",
  ]);
});

test("every failure toast carries the error tone", () => {
  assert.deepEqual(sourceFiles().flatMap((path) => untonedFailures(path)), []);
});
