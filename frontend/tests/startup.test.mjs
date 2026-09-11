import assert from "node:assert/strict";
import test from "node:test";

import { beforeFirstPaint } from "../src/lib/startup.ts";

const settleAfter = (ms, value, fail = false) =>
  new Promise((resolve, reject) => setTimeout(() => (fail ? reject(value) : resolve(value)), ms));

test("the first paint waits for the account when it answers in time", async () => {
  let answered = false;
  const work = settleAfter(20).then(() => { answered = true; });
  await beforeFirstPaint(work, 5_000);
  assert.ok(answered, "the page was drawn before the account answered");
});

test("a failed account lookup still lets the page draw", async () => {
  const started = Date.now();
  await beforeFirstPaint(settleAfter(10, new Error("offline"), true), 5_000);
  assert.ok(Date.now() - started < 1_000, "a rejection should release the paint at once");
});

test("a server that never answers costs the bound, not the page", async () => {
  const started = Date.now();
  await beforeFirstPaint(new Promise(() => {}), 30);
  const waited = Date.now() - started;
  assert.ok(waited >= 25 && waited < 1_000, `waited ${waited} ms for a bound of 30`);
});
