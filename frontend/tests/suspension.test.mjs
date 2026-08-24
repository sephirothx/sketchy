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
      expiresAt: "2026-08-25T12:00:00.000Z",
      messages: [{ text: "the thing they said", at: "2026-08-24T11:00:00.000Z" }],
    }),
    {
      reason: "Harassment",
      expiresAt: "2026-08-25T12:00:00.000Z",
      messages: [{ text: "the thing they said", at: "2026-08-24T11:00:00.000Z" }],
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
    expiresAt: null,
    messages: [],
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
