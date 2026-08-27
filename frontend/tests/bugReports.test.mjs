import assert from "node:assert/strict";
import test from "node:test";

import {
  BUG_AREAS,
  BUG_SEVERITIES,
  bugReportScreenshotUrl,
  bugReportTriageText,
  copyToClipboard,
  humanizeBugValue,
} from "../src/lib/bugReports.ts";

/** One report, fixed, so the format itself is what is under test. */
function aReport(overrides = {}) {
  return {
    id: "7c41a9de-0000-7000-8000-000000000001",
    reporterUserId: "5f2b9c81-0000-7000-8000-000000000002",
    reporter: { displayName: "Sparrow-14", registered: false, createdAt: "2026-08-24T09:00:00+00:00" },
    area: "drawing_and_canvas",
    severity: "blocks_play",
    summary: "Timer kept counting after everyone had guessed",
    details: "Round 2, everyone had guessed but the timer ran to zero.",
    buildSha: "a299f80",
    route: "/room/BQ7F2K",
    roomCode: "BQ7F2K",
    gameId: "4f2b9c81-0000-7000-8000-000000000003",
    turnId: "b7d0a35e-0000-7000-8000-000000000004",
    clientContext: {
      buildSha: "a299f80",
      viewport: { width: 1440, height: 900, dpr: 2 },
      recentErrors: [
        { at: "2026-08-27T09:40:51Z", kind: "console", message: "replay budget exceeded" },
        { at: "2026-08-27T09:41:02Z", kind: "error", message: "TypeError: ctx is null" },
      ],
    },
    serverContext: { game: { roundNumber: 2, isDrawer: false } },
    screenshot: {
      status: "ready",
      contentType: "image/webp",
      byteSize: 188416,
      width: 1440,
      height: 900,
      checksum: "a".repeat(64),
    },
    status: "pending",
    reviewedByUserId: null,
    resolutionNote: null,
    createdAt: "2026-08-27T09:41:12+00:00",
    updatedAt: "2026-08-27T09:41:12+00:00",
    reviewedAt: null,
    ...overrides,
  };
}

test("the triage block leads with the identity a reader needs first", () => {
  const lines = bugReportTriageText(aReport()).split("\n");
  assert.equal(lines[0], "# Sketchy bug report 7c41a9de-0000-7000-8000-000000000001");
  assert.equal(lines[1], "status: pending");
  assert.equal(lines[2], "filed: 2026-08-27T09:41:12+00:00");
  assert.match(lines[3], /^reporter: guest account, created /);
  assert.equal(lines[4], "area: drawing_and_canvas");
  assert.equal(lines[5], "severity: blocks_play");
});

test("every heading a reader or a model would look for is present", () => {
  const text = bugReportTriageText(aReport());
  for (const heading of [
    "## Summary",
    "## Details",
    "## Environment",
    "### Reported by the client",
    "### Observed by the server",
    "## Client errors (2, newest first)",
    "## Screenshot",
  ]) {
    assert.ok(text.includes(heading), `missing ${heading}`);
  }
});

test("identifiers are written out in full, never abbreviated for display", () => {
  const text = bugReportTriageText(aReport());
  assert.ok(text.includes("game_id: 4f2b9c81-0000-7000-8000-000000000003"));
  assert.ok(text.includes("turn_id: b7d0a35e-0000-7000-8000-000000000004"));
  assert.ok(text.includes("room: BQ7F2K"));
});

test("client errors are numbered newest first", () => {
  const text = bugReportTriageText(aReport());
  const first = text.indexOf("1. 2026-08-27T09:41:02Z error TypeError: ctx is null");
  const second = text.indexOf("2. 2026-08-27T09:40:51Z console replay budget exceeded");
  assert.ok(first > 0 && second > first);
});

test("nested context is flattened to one fact per line", () => {
  const text = bugReportTriageText(aReport());
  assert.ok(text.includes("viewport.width: 1440"));
  assert.ok(text.includes("game.isDrawer: false"));
});

test("a screenshot reports its shape, its URL and the server's digest", () => {
  const text = bugReportTriageText(aReport());
  assert.ok(text.includes("attached: 1440x900 image/webp 188416 bytes"));
  assert.ok(text.includes(`url: ${bugReportScreenshotUrl(aReport().id)}`));
  assert.ok(text.includes(`sha256: ${"a".repeat(64)}`));
});

test("an erased screenshot says so rather than reading as one that never existed", () => {
  const text = bugReportTriageText(
    aReport({ screenshot: { ...aReport().screenshot, status: "erased" } }),
  );
  assert.ok(text.includes("erased when the report was decided"));
  assert.ok(!text.includes("url: /api/admin"));
});

test("a report with nothing attached still produces every section", () => {
  const text = bugReportTriageText(
    aReport({
      reporter: null,
      roomCode: null,
      gameId: null,
      turnId: null,
      clientContext: {},
      serverContext: {},
      screenshot: { status: "none", contentType: null, byteSize: null, width: null, height: null, checksum: null },
    }),
  );
  assert.ok(text.includes("reporter: account since deleted"));
  assert.ok(text.includes("## Screenshot\nnone"));
  assert.ok(!text.includes("room:"));
  assert.ok(!text.includes("## Client errors"));
});

test("a decided report carries its note", () => {
  const text = bugReportTriageText(
    aReport({ status: "resolved", resolutionNote: "Fixed in a299f80.", reviewedAt: "2026-08-27T11:00:00+00:00" }),
  );
  assert.ok(text.includes("## Resolution"));
  assert.ok(text.includes("Fixed in a299f80."));
});

test("the offered areas match the values the server accepts", () => {
  assert.deepEqual(
    BUG_AREAS.map((entry) => entry.value),
    [
      "drawing_and_canvas",
      "guessing_and_chat",
      "rounds_and_scoring",
      "rooms_and_lobby",
      "prompt_lists",
      "account_and_settings",
      "connection_and_sync",
      "performance",
      "accessibility",
      "other",
    ],
  );
  assert.deepEqual(
    BUG_SEVERITIES.map((entry) => entry.value),
    ["blocks_play", "major", "minor"],
  );
});

test("stored values are shown as words", () => {
  assert.equal(humanizeBugValue("drawing_and_canvas"), "Drawing and canvas");
  assert.equal(humanizeBugValue("blocks_play"), "Blocks play");
});


/* ------------------------------------------------------------- clipboard */

function stubClipboard({ writeText, execCommand } = {}) {
  const carriers = [];
  // Node's own `navigator` is getter-only, so it has to be redefined.
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { clipboard: writeText ? { writeText } : {} },
  });
  globalThis.document = {
    createElement: () => {
      const node = { value: "", style: {}, setAttribute() {}, select() {} };
      carriers.push(node);
      return node;
    },
    body: { appendChild() {}, removeChild() {} },
    execCommand: execCommand ?? (() => false),
  };
  return carriers;
}

test("the clipboard API is used when the browser allows it", async () => {
  const written = [];
  stubClipboard({ writeText: async (text) => written.push(text) });
  assert.equal(await copyToClipboard("hello"), true);
  assert.deepEqual(written, ["hello"]);
});

test("a refused clipboard API falls back rather than giving up", async () => {
  // An insecure origin, a missing permission, or a click the browser did not
  // count as activation - all of which an operator meets in the wild.
  const carriers = stubClipboard({
    writeText: async () => {
      throw new Error("NotAllowedError");
    },
    execCommand: () => true,
  });
  assert.equal(await copyToClipboard("fallback text"), true);
  assert.equal(carriers[0].value, "fallback text");
});

test("a browser with no clipboard route at all reports failure honestly", async () => {
  stubClipboard({ execCommand: () => false });
  assert.equal(await copyToClipboard("nowhere"), false);
});
