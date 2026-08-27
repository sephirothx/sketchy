import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";

import {
  MAX_ENTRIES,
  MAX_MESSAGE_CHARS,
  installClientErrorLog,
  recentClientErrors,
  recordClientError,
  resetClientErrorLog,
} from "../src/lib/clientErrorLog.ts";

// Node has no window; the recorder only needs somewhere to hang listeners, and
// the browser events themselves are exercised end to end rather than here.
const listeners = new Map();
globalThis.window = {
  addEventListener: (name, handler) => listeners.set(name, handler),
};

beforeEach(() => {
  resetClientErrorLog();
  listeners.clear();
});

test("the buffer keeps the newest entries and drops the oldest", () => {
  for (let index = 0; index < MAX_ENTRIES + 12; index += 1) {
    recordClientError("console", `error ${index}`);
  }
  const entries = recentClientErrors();
  assert.equal(entries.length, MAX_ENTRIES);
  // The tail that survives is the one that actually preceded the failure.
  assert.equal(entries.at(-1).message, `error ${MAX_ENTRIES + 11}`);
  assert.equal(entries[0].message, "error 12");
});

test("a long message is trimmed rather than dropped", () => {
  recordClientError("error", "x".repeat(4000));
  assert.equal(recentClientErrors()[0].message.length, MAX_MESSAGE_CHARS);
});

test("an Error keeps its name, message and stack", () => {
  recordClientError("error", new TypeError("cannot read properties of null"));
  const [entry] = recentClientErrors();
  assert.match(entry.message, /^TypeError: cannot read properties of null/);
});

test("a value that cannot be serialized is still recorded", () => {
  const circular = {};
  circular.self = circular;
  recordClientError("console", circular);
  assert.equal(recentClientErrors().length, 1);
});

test("the returned tail is a copy, so a caller cannot rewrite history", () => {
  recordClientError("console", "original");
  const entries = recentClientErrors();
  entries[0].message = "tampered";
  entries.push({ at: "", kind: "console", message: "invented" });
  assert.deepEqual(
    recentClientErrors().map((entry) => entry.message),
    ["original"],
  );
});

test("console.error is recorded and still reaches the real console", () => {
  const seen = [];
  const original = console.error;
  console.error = (...args) => seen.push(args.join(" "));
  try {
    installClientErrorLog();
    console.error("boom", 42);
  } finally {
    console.error = original;
  }
  assert.deepEqual(seen, ["boom 42"]);
  assert.equal(recentClientErrors().at(-1).message, "boom 42");
});

test("an uncaught error is recorded with where it came from", () => {
  installClientErrorLog();
  listeners.get("error")({
    error: new RangeError("out of range"),
    filename: "/assets/canvas.js",
    lineno: 42,
  });
  assert.match(recentClientErrors()[0].message, /RangeError: out of range/);
  assert.match(recentClientErrors()[0].message, /\/assets\/canvas\.js:42/);
});

test("a rejected promise nobody handled is recorded", () => {
  installClientErrorLog();
  listeners.get("unhandledrejection")({ reason: new Error("no ack") });
  assert.equal(recentClientErrors()[0].kind, "unhandled");
});

test("a reset unwraps the console, so installs cannot stack", () => {
  // Without the unwrap, the second install wraps the first wrapper and one
  // console.error is recorded twice - and three times after a third install.
  const seen = [];
  const original = console.error;
  console.error = (...args) => seen.push(args.join(" "));
  try {
    installClientErrorLog();
    resetClientErrorLog();
    installClientErrorLog();
    resetClientErrorLog();
    installClientErrorLog();
    console.error("once");
    assert.deepEqual(
      recentClientErrors().map((entry) => entry.message),
      ["once"],
    );
    // And the real console still heard it exactly once.
    assert.deepEqual(seen, ["once"]);
  } finally {
    resetClientErrorLog();
    console.error = original;
  }
});

test("a reset leaves the console exactly as it found it", () => {
  const sentinel = () => {};
  const original = console.error;
  console.error = sentinel;
  try {
    installClientErrorLog();
    assert.notEqual(console.error, sentinel, "install should have wrapped it");
    resetClientErrorLog();
    assert.equal(console.error, sentinel);
  } finally {
    console.error = original;
  }
});

test("recording cannot recurse when the recorder itself logs", () => {
  const original = console.error;
  console.error = () => {
    // A wrapper that logs while being logged is the loop the guard exists for.
    recordClientError("console", "from inside");
  };
  try {
    installClientErrorLog();
    console.error("outer");
  } finally {
    console.error = original;
  }
  assert.ok(recentClientErrors().length <= MAX_ENTRIES);
});
