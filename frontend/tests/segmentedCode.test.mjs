import assert from "node:assert/strict";
import test from "node:test";

/**
 * The rule the six boxes encode, tested where it lives — as a value handed
 * to the caller rather than left in React state.
 *
 * The bug this pins: the last digit typed has not reached state when the row
 * asks to submit, so a form reading `code` there sends five digits. Whatever
 * completes the code must travel with the completion.
 */
function completion(previous, index, typed, length = 6) {
  const digits = typed.replace(/\D/g, "");
  const next =
    digits.length > 1
      ? digits.slice(0, length)
      : (previous.slice(0, index) + digits.slice(-1) + previous.slice(index + 1)).slice(0, length);
  return { value: next, complete: next.length === length ? next : null };
}

test("the digit that completes the code is the one handed over", () => {
  const { value, complete } = completion("12345", 5, "6");
  assert.equal(value, "123456");
  assert.equal(complete, "123456", "not the five digits state still holds");
});

test("an incomplete code completes nothing", () => {
  assert.equal(completion("1234", 4, "5").complete, null);
});

test("a pasted code fills the row whatever its punctuation", () => {
  for (const pasted of ["123456", "123 456", "123-456"]) {
    assert.equal(completion("", 0, pasted).complete, "123456", pasted);
  }
});

test("a paste longer than the row is cut to it", () => {
  assert.equal(completion("", 0, "1234567890").complete, "123456");
});

test("letters are not digits", () => {
  assert.equal(completion("12345", 5, "x").value, "12345");
});
