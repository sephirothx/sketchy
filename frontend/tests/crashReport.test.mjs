import assert from "node:assert/strict";
import test from "node:test";

import {
  DIAGNOSTIC_DIVIDER,
  MAX_DETAILS_CHARS,
  MAX_DIAGNOSTIC_CHARS,
  MAX_SUMMARY_CHARS,
  composeDetails,
  crashArea,
  playerTextBudget,
  prefillCrashReport,
  redactDiagnostic,
} from "../src/lib/crashReport.ts";

test("a query string is cut from a URL and from a bare path", () => {
  assert.equal(
    redactDiagnostic("fetch https://sketchy.example/api/rooms?code=BQ7F2K&x=1 failed"),
    "fetch https://sketchy.example/api/rooms?*** failed",
  );
  assert.equal(redactDiagnostic("at /room/BQ7F2K?invite=abc (x.js:1)"), "at /room/BQ7F2K?*** (x.js:1)");
});

test("secrets named as such are masked, however they are joined", () => {
  assert.equal(redactDiagnostic("token=abc.def"), "token=***");
  assert.equal(redactDiagnostic("Api-Key: 1234"), "Api-Key: ***");
  assert.equal(redactDiagnostic("Authorization: Bearer eyJhbGci.x-y"), "Authorization: Bearer ***");
  assert.equal(redactDiagnostic("sketchy_session = 9f8e"), "sketchy_session = ***");
});

test("credentials inside a URL and the local part of an address go", () => {
  assert.equal(
    redactDiagnostic("postgresql://sketchy:hunter2@db.internal/app"),
    "postgresql://sketchy:***@db.internal/app",
  );
  assert.equal(redactDiagnostic("sent to marta.k+tag@example.org"), "sent to ***@example.org");
});

test("the area follows the scope first, then the page", () => {
  assert.equal(crashArea("room", "/room/BQ7F2K", "drawing"), "drawing_and_canvas");
  assert.equal(crashArea("room", "/room/BQ7F2K", "idle"), "rooms_and_lobby");
  assert.equal(crashArea("app", "/", null), "rooms_and_lobby");
  assert.equal(crashArea("app", "/room/BQ7F2K?x=1", null), "rooms_and_lobby");
  assert.equal(crashArea("app", "/prompt-lists/animals", null), "prompt_lists");
  assert.equal(crashArea("app", "/my-prompt-lists", null), "prompt_lists");
  assert.equal(crashArea("app", "/settings/appearance", null), "account_and_settings");
  assert.equal(crashArea("app", "/profile", null), "account_and_settings");
  assert.equal(crashArea("app", "/reset-password", null), "account_and_settings");
  assert.equal(crashArea("app", "/admin/operations", null), "other");
  assert.equal(crashArea("app", "/nowhere", null), "other");
});

test("the summary names the page and the error, path only, within the limit", () => {
  const error = new TypeError("Cannot read properties of null (reading 'players')");
  const { summary, severity } = prefillCrashReport({
    scope: "room",
    route: "/room/BQ7F2K?invite=1",
    error,
    componentStack: null,
  });
  assert.equal(summary, "Crash on /room/BQ7F2K: TypeError: Cannot read properties of null (reading 'players')");
  assert.equal(severity, "blocks_play");

  const long = prefillCrashReport({
    scope: "app",
    route: "/",
    error: new Error("x".repeat(500)),
    componentStack: null,
  });
  assert.equal(long.summary.length, MAX_SUMMARY_CHARS);
});

test("the diagnostic block carries the scope, page, error, stack and tree", () => {
  const error = new RangeError("out of range");
  error.stack = "RangeError: out of range\n    at draw (/assets/canvas.js:10:5)\n    at render (/assets/app.js:2:1)";
  const { diagnosticBlock } = prefillCrashReport({
    scope: "app",
    route: "/prompt-lists",
    error,
    componentStack: "\n    at Toolbar\n    at GameplayRegion\n    at App",
  });
  assert.equal(
    diagnosticBlock,
    [
      "Scope: application root",
      "Page: /prompt-lists",
      "Error: RangeError: out of range",
      "Stack:",
      "  at draw (/assets/canvas.js:10:5)",
      "  at render (/assets/app.js:2:1)",
      "Component tree:",
      "  at Toolbar",
      "  at GameplayRegion",
      "  at App",
    ].join("\n"),
  );
});

test("a redaction reaches into the error message and the stack", () => {
  const error = new Error("refused for marta@example.org with token=abc");
  error.stack = "Error: refused\n    at f (https://sketchy.example/assets/a.js?v=123:1:1)";
  const { summary, diagnosticBlock } = prefillCrashReport({
    scope: "app", route: "/", error, componentStack: null,
  });
  assert.match(summary, /\*\*\*@example\.org with token=\*\*\*/);
  assert.doesNotMatch(summary, /marta|abc/);
  // The query takes the line and column with it: after `?` everything up to
  // the closing bracket is query, and a fingerprinted asset never has one.
  assert.match(diagnosticBlock, /at f \(https:\/\/sketchy\.example\/assets\/a\.js\?\*\*\*\)/);
  assert.doesNotMatch(diagnosticBlock, /Error: refused\n/);
});

test("something thrown that is not an Error still makes a report", () => {
  const { summary, diagnosticBlock } = prefillCrashReport({
    scope: "app", route: "/", error: { code: 7 }, componentStack: null,
  });
  assert.equal(summary, 'Crash on /: Thrown value: {"code":7}');
  assert.doesNotMatch(diagnosticBlock, /Stack:/);
});

test("the diagnostic never takes more than its share of the details", () => {
  const error = new Error("m");
  error.stack = "Error: m\n" + Array.from({ length: 8 }, (_, i) => `    at f${i} (${"x".repeat(400)}:1:1)`).join("\n");
  const { diagnosticBlock } = prefillCrashReport({ scope: "app", route: "/", error, componentStack: null });
  assert.equal(diagnosticBlock.length, MAX_DIAGNOSTIC_CHARS);
  assert.ok(playerTextBudget(diagnosticBlock) >= 1400);
});

test("details put the player's words first and the diagnostic under a divider", () => {
  const details = composeDetails("  I clicked Start game.  ", "Scope: live room\nPage: /room/AAAAAA");
  assert.equal(details, `I clicked Start game.\n\n${DIAGNOSTIC_DIVIDER}\nScope: live room\nPage: /room/AAAAAA`);
});

test("no words from the player still leaves a valid, non-empty details field", () => {
  const details = composeDetails("   ", "Scope: application root");
  assert.equal(details, `${DIAGNOSTIC_DIVIDER}\nScope: application root`);
  assert.equal(composeDetails("just words", ""), "just words");
});

test("a long description is cut to its budget rather than cutting the diagnostic", () => {
  const block = "B".repeat(1000);
  const details = composeDetails("A".repeat(10_000), block);
  assert.equal(details.length, MAX_DETAILS_CHARS);
  assert.ok(details.endsWith(block), "the diagnostic survives intact at the end");
  assert.equal(playerTextBudget(""), MAX_DETAILS_CHARS);
});
