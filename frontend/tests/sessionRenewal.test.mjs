import assert from "node:assert/strict";
import test from "node:test";
import { Worker } from "node:worker_threads";

import { announceSessionRenewed, onSessionRenewed } from "../src/lib/sessionRenewal.ts";

const heard = (stop, timeoutMs) =>
  new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs);
    stop.resolve = () => {
      clearTimeout(timer);
      resolve(true);
    };
  });

test("another tab's renewal reaches this one's listener (#1295 review)", async () => {
  const signal = {};
  const waiting = heard(signal, 2000);
  const stop = onSessionRenewed(() => signal.resolve());
  // Another tab: a separate context posting on the same channel name.
  const other = new Worker(
    `const channel = new BroadcastChannel("sketchy-session");
     channel.postMessage({ type: "renewed", from: "another-tab" });
     channel.close();`,
    { eval: true },
  );
  try {
    assert.equal(await waiting, true);
  } finally {
    stop();
    await other.terminate();
  }
});

test("a tab does not answer its own announcement, having rebound already", async () => {
  const signal = {};
  const waiting = heard(signal, 300);
  const stop = onSessionRenewed(() => signal.resolve());
  try {
    announceSessionRenewed();
    assert.equal(await waiting, false);
  } finally {
    stop();
  }
});
