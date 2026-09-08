import assert from "node:assert/strict";
import test from "node:test";

import { authSubmitter } from "../src/lib/authSubmit.ts";

/** The dialog collects four things and two functions want three each, in a
 * different order. Nothing in the type system objects to handing one where
 * the other is expected — a three-parameter function is assignable to a
 * four-parameter type — so the mistake this covers compiled cleanly and
 * dropped the second factor on the floor: a staff account typed its code,
 * the server was asked to accept a sign-in with none, and answered "enter
 * the code from your authenticator app" to somebody looking at the code they
 * had just entered. */

function recorder() {
  const calls = [];
  return [calls, (...args) => { calls.push(args); return Promise.resolve({ id: "u" }); }];
}

test("signing in sends the code, and never the email", async () => {
  const [logins, login] = recorder();
  const [registrations, register] = recorder();

  await authSubmitter("login", login, register)({
    username: "Marta",
    password: "a-good-password",
    email: "marta@example.test",
    code: "123456",
  });

  assert.deepEqual(logins, [["Marta", "a-good-password", "123456"]]);
  assert.deepEqual(registrations, []);
});

test("claiming an account sends the email, and never the code", async () => {
  const [logins, login] = recorder();
  const [registrations, register] = recorder();

  await authSubmitter("claim", login, register)({
    username: "Marta",
    password: "a-good-password",
    email: "marta@example.test",
  });

  assert.deepEqual(registrations, [["Marta", "a-good-password", "marta@example.test"]]);
  assert.deepEqual(logins, []);
});

test("what was not typed is not sent", async () => {
  // An ordinary sign-in: no second factor, no email. Both must arrive as
  // absent rather than as an empty string, which the server would read as an
  // answer that was given and was wrong.
  const [logins, login] = recorder();
  const [, register] = recorder();

  await authSubmitter("login", login, register)({
    username: "Marta",
    password: "a-good-password",
  });

  assert.deepEqual(logins, [["Marta", "a-good-password", undefined]]);
});
