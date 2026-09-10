import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../src/lib/api.ts";
import { refusalCode, refusalText } from "../src/lib/refusals.ts";

test("a refusal is read from its code, not from the server's sentence", () => {
  const problem = new ApiError(404, "No such player.", { errorCode: "no_such_player" });
  assert.equal(refusalCode(problem), "no_such_player");
  assert.equal(refusalText(problem, "fallback"), "No such player.");
});

test("the sentence comes from the table even when the server's prose differs", () => {
  // The server's `detail` is English for the log. Changing it must not change
  // a word on screen - that is the whole point of the split.
  const problem = new ApiError(401, "whatever the server logged", {
    errorCode: "sign_in_required",
  });
  assert.equal(refusalText(problem, "fallback"), "Sign in first.");
});

test("a failure with no code falls back to the caller's own sentence", () => {
  // A timeout, a proxy, a 502: there is no body and so no code, and the
  // caller knows better than this module what it was trying to do.
  assert.equal(refusalText(new Error("network"), "Could not save that preset."),
    "Could not save that preset.");
  assert.equal(refusalText(null, "Could not save that preset."),
    "Could not save that preset.");
  assert.equal(refusalText({ errorCode: "from_a_newer_server" }, "Something went wrong."),
    "Something went wrong.");
});

test("a socket acknowledgement is read the same way as an HTTP refusal", () => {
  const ack = { ok: false, errorCode: "room_full", error: "Room is full" };
  assert.equal(refusalText(ack, "Could not join."), "This room is full.");
});

test("params supply the values a sentence needs, never its words", () => {
  const tooLarge = new ApiError(422, "too large", {
    errorCode: "screenshot_too_large",
    params: { limitBytes: 2_000_000 },
  });
  assert.equal(
    refusalText(tooLarge, "fallback"),
    "That screenshot is too large. The limit is 2 MB.",
  );

  const full = { errorCode: "block_list_full", params: { limit: 200 } };
  assert.match(refusalText(full, "fallback"), /200/);
});

test("a weak password says which rule refused it", () => {
  // A refusal somebody cannot act on sends them back with the same password
  // and one more digit (R-AUTH-19), so the reason travels as a slug.
  const cases = [
    [{ reason: "too_short", detail: 12 }, /at least 12 characters/],
    [{ reason: "keyboard_walk" }, /run of keys in order/],
    [{ reason: "contains_identity" }, /must not contain your name/],
    [{ reason: "too_few_characters", detail: 3 }, /only 3 different characters/],
  ];
  for (const [params, expected] of cases) {
    const problem = new ApiError(400, "policy", { errorCode: "weak_password", params });
    assert.match(refusalText(problem, "fallback"), expected);
  }
});

test("a reason the client has never heard of still says something useful", () => {
  const problem = new ApiError(400, "policy", {
    errorCode: "weak_password",
    params: { reason: "invented_later" },
  });
  assert.equal(refusalText(problem, "fallback"), "Please choose a different password.");
});

test("account_required names the thing it refused", () => {
  const forAvatar = { errorCode: "account_required", params: { action: "avatar" } };
  const forLists = { errorCode: "account_required", params: { action: "prompt_lists" } };
  assert.equal(refusalText(forAvatar, "f"), "Create an account to choose a picture.");
  assert.equal(refusalText(forLists, "f"), "Create an account to save reusable prompt lists.");
  assert.equal(refusalText({ errorCode: "account_required" }, "f"), "Create an account to do that.");
});

test("an ApiError carries the field and retry a form needs", () => {
  const problem = new ApiError(429, "slow down", {
    errorCode: "too_many_attempts",
    field: "password",
    retryAfterMs: 30_000,
  });
  assert.equal(problem.field, "password");
  assert.equal(problem.retryAfterMs, 30_000);
  assert.equal(problem.status, 429);
});
