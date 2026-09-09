import assert from "node:assert/strict";
import test from "node:test";

import {
  reportedMessages,
  suspensionDuration,
  suspensionFromPayload,
} from "../src/lib/suspension.ts";

test("the refusal for a suspended account is recognised, and nothing else is", () => {
  assert.deepEqual(
    suspensionFromPayload({
      detail: "This account is suspended.",
      suspended: true,
      reason: "Harassment",
      category: "harassment",
      expiresAt: "2026-08-25T12:00:00.000Z",
      messages: [{ text: "the thing they said", at: "2026-08-24T11:00:00.000Z" }],
    }),
    {
      reason: "Harassment",
      category: "harassment",
      expiresAt: "2026-08-25T12:00:00.000Z",
      messages: [{ text: "the thing they said", at: "2026-08-24T11:00:00.000Z" }],
      drawings: [],
    },
  );

  // An ordinary 403 is not a suspension, and must not raise the notice.
  assert.equal(suspensionFromPayload({ detail: "Moderator access required." }), null);
  assert.equal(suspensionFromPayload(null), null);
  assert.equal(suspensionFromPayload("suspended"), null);
});

test("a suspension with no reason recorded is still a suspension", () => {
  // The ban row may be gone by the time the refusal is built; saying less is
  // better than saying nothing.
  assert.deepEqual(suspensionFromPayload({ suspended: true }), {
    reason: null,
    category: null,
    expiresAt: null,
    messages: [],
    drawings: [],
  });
});

test("how long it lasts is stated, and 'no end date' is not called forever", () => {
  const now = new Date("2026-08-24T12:00:00.000Z");

  assert.match(
    suspensionDuration({ reason: null, expiresAt: "2026-08-25T12:00:00.000Z", messages: [] }, now),
    /lasts until/,
  );
  assert.match(
    suspensionDuration({ reason: null, expiresAt: null, messages: [] }, now),
    /no end date/,
  );
  // A suspension nobody put an end on is not the same claim as "forever".
  assert.doesNotMatch(
    suspensionDuration({ reason: null, expiresAt: null, messages: [] }, now),
    /forever|permanent/i,
  );
});

test("a suspension whose end has passed says to try again", () => {
  const now = new Date("2026-08-26T12:00:00.000Z");

  assert.match(
    suspensionDuration({ reason: null, expiresAt: "2026-08-25T12:00:00.000Z", messages: [] }, now),
    /has ended/,
  );
});

test("an unreadable expiry is treated as no end date rather than crashing", () => {
  assert.match(
    suspensionDuration({ reason: null, expiresAt: "not a date", messages: [] }),
    /no end date/,
  );
});

test("a malformed message is dropped rather than rendered", () => {
  // Somebody already having a bad day should not be shown "undefined".
  assert.deepEqual(
    reportedMessages([
      { text: "kept", at: "2026-08-24T11:00:00.000Z" },
      { text: "kept without a time" },
      { at: "2026-08-24T11:00:00.000Z" },
      null,
      "not a message",
    ]),
    [
      { text: "kept", at: "2026-08-24T11:00:00.000Z" },
      { text: "kept without a time", at: null },
    ],
  );
  assert.deepEqual(reportedMessages(undefined), []);
});


test("a suspension refusal carries every reported drawing by its metadata", () => {
  // One per reporter who attached the canvas as it stood when they sent, so
  // the notice shows the drawing as it changed under them rather than
  // whichever report the suspension happens to name.
  const suspension = suspensionFromPayload({
    suspended: true,
    reason: "Not a toaster.",
    expiresAt: null,
    messages: [],
    drawings: [
      { reportId: "r1", turnId: "t1", roundNumber: 2, prompt: "toaster", actionCount: 3, byteSize: 90, capturedAt: "2026-09-05T18:00:00Z" },
      { reportId: "r2", turnId: "t1", roundNumber: 2, prompt: "toaster", actionCount: 9, byteSize: 140, capturedAt: "2026-09-05T18:00:40Z" },
    ],
  });
  assert.equal(suspension?.drawings.length, 2);
  assert.equal(suspension?.drawings[0].prompt, "toaster");
  assert.equal(suspension?.drawings[0].roundNumber, 2);
  // Each names the report whose bytes may then be fetched.
  assert.deepEqual(suspension?.drawings.map((entry) => entry.reportId), ["r1", "r2"]);
});

test("a malformed drawing on a refusal is dropped rather than rendered", () => {
  // A drawing without its report id names nothing to fetch, so it is no more
  // renderable than one with a broken prompt.
  const suspension = suspensionFromPayload({
    suspended: true,
    drawings: [
      { reportId: "r1", prompt: 7 },
      { turnId: "t1", prompt: "toaster" },
      { reportId: "r3", turnId: "t3", prompt: "kept", roundNumber: 1, actionCount: 1, byteSize: 5, capturedAt: "" },
    ],
  });
  assert.deepEqual(suspension?.drawings.map((entry) => entry.prompt), ["kept"]);
});
