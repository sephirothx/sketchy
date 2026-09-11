/** The server's prose never reaches a player's screen.

A refusal, a removal notice or an acknowledgement crosses the wire as a code
and an English sentence: the code is for the client to say something with, in
the reader's language, and the sentence is for a log (R-I18N-01). No compiler
tells the two apart - `error.message` is as good a string as any - so this
reads the tree for the shapes that print the server's words: a `.message` or
`.detail` read, and an `.error` or `.reason` field with a fallback behind it
(`data?.reason || ui.x.y` is the server's sentence whenever there is one).

A read that is not the server's prose is listed below with the reason it is
not, so a new one has to be looked at before it ships, and an entry nothing
reads any more fails too. This replaces a regex in
`backend/tests/test_rest_refusals.py` that saw one spelling of the first shape
and none of the second. */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";

const ROOT = "src";
const EXEMPT = [
  // Staff surfaces, read by operators in English (R-I18N-01).
  "pages/ops/", "pages/AdminOperationsPage", "pages/ModerationPage", "pages/BugReportsPage",
  "lib/operations", "lib/adminControls", "lib/moderation",
  // A crash report and the error log are read by an operator.
  "lib/crashReport", "lib/clientErrorLog",
  "content/",
];

const REVIEWED = {
  "lib/api.ts: payload.detail": "read to become the ApiError's own message, which is for a log",
  "components/ConfettiCanvas.tsx: customEv.detail": "a DOM CustomEvent's payload, not the server's",
  "components/BugReportDialog.tsx: entry.message":
    "an error-log line, shown verbatim as part of what the report will send",
  "pages/CrashPage.tsx: entry.message": "the same, on the crash page",
  "lib/bugReports.ts: entry.message": "the staff triage text, pasted into an issue in English",
  "lib/socket.ts: error?.message": "a transport failure, recorded in the client error log",
  "components/InviteEntryPage.tsx: state.message": "a room-entry state, written from the catalogue",
  "components/PictureCropDialog.tsx: failure.message": "an AvatarInputError, thrown with catalogue text",
  "components/ToastProvider.tsx: toast.message": "a toast's own text, written by whoever raised it",
  "components/LobbyChatPanel.tsx: error.message":
    "an IdentityRequiredError, thrown with the name check's catalogue text",
  "pages/LobbyBrowserPage.tsx: error.message": "the same",
  "lib/suspension.ts: body.reason":
    "the moderator's own words to the player, shown as written - a person's, not the server's",
  "components/SuspensionNotice.tsx: body.reason": "the same, as it arrives on the socket",
  "components/InviteEntryPage.tsx: state.error":
    "a room-entry state's error, always written on this side (refusalText or the catalogue)",
};

function sourceFiles(dir = ROOT, out = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) sourceFiles(path, out);
    else if (/\.tsx?$/.test(path)) out.push(path);
  }
  return out;
}

function readsIn(path, text = readFileSync(path, "utf8")) {
  const source = ts.createSourceFile(
    path, text, ts.ScriptTarget.Latest, true,
    /\.tsx$/.test(path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const rel = relative(ROOT, path);
  const found = [];
  const visit = (node) => {
    if (ts.isPropertyAccessExpression(node)) {
      const name = node.name.text;
      let child = node;
      let parent = node.parent;
      while (ts.isParenthesizedExpression(parent) || ts.isNonNullExpression(parent) || ts.isAsExpression(parent)) {
        child = parent;
        parent = parent.parent;
      }
      const leftOf = (...kinds) => ts.isBinaryExpression(parent) && parent.left === child
        && kinds.includes(parent.operatorToken.kind);
      const withFallback = leftOf(ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken);
      // `ok ? notice.reason : ui.x.y` picks the server's words as surely as `||`.
      const branch = ts.isConditionalExpression(parent) && parent.condition !== child;
      const assigned = leftOf(ts.SyntaxKind.EqualsToken);
      if (!assigned && (name === "message" || name === "detail"
        || ((name === "error" || name === "reason") && (withFallback || branch)))) {
        found.push(`${rel}: ${node.getText(source)}`);
      }
    }
    // `const { detail } = await …` reads the field without a dot in sight.
    // Only a declaration: a component's own props are not the server's.
    if (ts.isBindingElement(node) && ts.isObjectBindingPattern(node.parent)
      && ts.isVariableDeclaration(node.parent.parent)) {
      const field = (node.propertyName ?? node.name).getText(source);
      if (["message", "detail", "reason"].includes(field)) found.push(`${rel}: { ${field} }`);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

function allReads() {
  return new Set(
    sourceFiles()
      .filter((path) => !EXEMPT.some((prefix) => relative(ROOT, path).startsWith(prefix)))
      .flatMap((path) => readsIn(path)),
  );
}

test("no player-facing screen prints the server's own words", () => {
  const unreviewed = [...allReads()].filter((read) => !(read in REVIEWED)).sort();
  assert.deepEqual(
    unreviewed,
    [],
    "these read what the server wrote. Say it from the code with "
      + "`refusalText(problem, fallback)` (or the code's own table), or - if it is "
      + `not the server's prose at all - add it to REVIEWED with why:\n${unreviewed.join("\n")}`,
  );
});

test("every reviewed read still exists", () => {
  const reads = allReads();
  const stale = Object.keys(REVIEWED).filter((read) => !reads.has(read));
  assert.deepEqual(stale, [], "an exemption for a read nothing makes any more is a hole waiting");
});

test("the scan sees the shapes that print the server's words", () => {
  const probe = (snippet) => readsIn(join(ROOT, "__probe__.tsx"), snippet).length > 0;
  for (const snippet of [
    "setError(problem.message);",
    "notify(data?.reason || ui.activeGameRoom.youWereKickedFromThe);",
    "setError(response.error ?? ui.x.y);",
    "const shown = payload.detail;",
    "function f(error) { if (error instanceof ApiError) return error.message; }",
    // The two forms #780's review found, verbatim.
    'serverFullReason = typeof notice?.reason === "string" && notice.reason\n'
      + "  ? notice.reason\n  : ui.socket.sketchyIsFullRightNow;",
    "const { detail } = await requestPasswordReset(identifier.trim());",
    "const { reason: why } = payload;",
  ]) {
    assert.ok(probe(snippet), `the scan cannot see: ${snippet}`);
  }
  for (const snippet of [
    "setError(refusalText(problem, ui.x.y));",
    "const reason = row.reason;",
    "if (response.error) retry();",
    'const kind = row.reason === "spam" ? "a" : "b";',
    "function Notice({ message }) { return message; }",
  ]) {
    assert.ok(!probe(snippet), `the scan objects to something harmless: ${snippet}`);
  }
});
