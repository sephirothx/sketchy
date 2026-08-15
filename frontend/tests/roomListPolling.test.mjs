import assert from "node:assert/strict";
import test from "node:test";

import { startVisibilityAwarePolling } from "../src/lib/roomListPolling.ts";

function createEnvironment(initialVisibility = "visible") {
  let visibility = initialVisibility;
  let nextIntervalId = 1;
  const listeners = new Set();
  const intervals = new Map();

  const environment = {
    visibilityState: () => visibility,
    addVisibilityChangeListener: (listener) => listeners.add(listener),
    removeVisibilityChangeListener: (listener) => listeners.delete(listener),
    setInterval: (listener) => {
      const intervalId = nextIntervalId++;
      intervals.set(intervalId, listener);
      return intervalId;
    },
    clearInterval: (intervalId) => intervals.delete(intervalId),
  };

  return {
    environment,
    listenerCount: () => listeners.size,
    intervalCount: () => intervals.size,
    setVisibility(nextVisibility) {
      visibility = nextVisibility;
      for (const listener of listeners) listener();
    },
    tick() {
      for (const listener of [...intervals.values()]) listener();
    },
  };
}

async function flushPromises() {
  await new Promise((resolve) => setImmediate(resolve));
}

test("visible polling refreshes immediately and on one interval", async () => {
  const fake = createEnvironment();
  let refreshes = 0;
  const dispose = startVisibilityAwarePolling(
    async () => {
      refreshes += 1;
    },
    4_000,
    fake.environment,
  );

  await flushPromises();
  assert.equal(refreshes, 1);
  assert.equal(fake.intervalCount(), 1);
  assert.equal(fake.listenerCount(), 1);

  fake.tick();
  await flushPromises();
  assert.equal(refreshes, 2);
  assert.equal(fake.intervalCount(), 1);

  dispose();
});

test("hidden polling waits for visibility and pauses again when hidden", async () => {
  const fake = createEnvironment("hidden");
  let refreshes = 0;
  const dispose = startVisibilityAwarePolling(
    async () => {
      refreshes += 1;
    },
    4_000,
    fake.environment,
  );

  await flushPromises();
  assert.equal(refreshes, 0);
  assert.equal(fake.intervalCount(), 0);

  fake.setVisibility("visible");
  await flushPromises();
  assert.equal(refreshes, 1);
  assert.equal(fake.intervalCount(), 1);

  fake.setVisibility("hidden");
  fake.tick();
  await flushPromises();
  assert.equal(refreshes, 1);
  assert.equal(fake.intervalCount(), 0);

  dispose();
});

test("visibility events do not overlap refreshes or duplicate intervals", async () => {
  const fake = createEnvironment();
  let refreshes = 0;
  let finishRefresh;
  const dispose = startVisibilityAwarePolling(
    () => {
      refreshes += 1;
      return new Promise((resolve) => {
        finishRefresh = resolve;
      });
    },
    4_000,
    fake.environment,
  );

  await flushPromises();
  assert.equal(refreshes, 1);

  fake.tick();
  fake.setVisibility("hidden");
  fake.setVisibility("visible");
  fake.setVisibility("visible");
  await flushPromises();
  assert.equal(refreshes, 1);
  assert.equal(fake.intervalCount(), 1);

  finishRefresh();
  await flushPromises();
  fake.tick();
  await flushPromises();
  assert.equal(refreshes, 2);

  dispose();
});

test("dispose removes lifecycle work and is idempotent", async () => {
  const fake = createEnvironment();
  let refreshes = 0;
  const dispose = startVisibilityAwarePolling(
    async () => {
      refreshes += 1;
    },
    4_000,
    fake.environment,
  );

  await flushPromises();
  dispose();
  dispose();
  assert.equal(fake.listenerCount(), 0);
  assert.equal(fake.intervalCount(), 0);

  fake.tick();
  fake.setVisibility("hidden");
  fake.setVisibility("visible");
  await flushPromises();
  assert.equal(refreshes, 1);
});

test("dispose during an in-flight refresh prevents later lifecycle work", async () => {
  const fake = createEnvironment();
  let refreshes = 0;
  let finishRefresh;
  const dispose = startVisibilityAwarePolling(
    () => {
      refreshes += 1;
      return new Promise((resolve) => {
        finishRefresh = resolve;
      });
    },
    4_000,
    fake.environment,
  );

  await flushPromises();
  assert.equal(refreshes, 1);

  dispose();
  assert.equal(fake.listenerCount(), 0);
  assert.equal(fake.intervalCount(), 0);

  finishRefresh();
  await flushPromises();
  fake.tick();
  fake.setVisibility("hidden");
  fake.setVisibility("visible");
  await flushPromises();
  assert.equal(refreshes, 1);
});
