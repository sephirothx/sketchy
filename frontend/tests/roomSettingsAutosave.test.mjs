import assert from "node:assert/strict";
import test from "node:test";

import {
  SAVED_STATUS_MS,
  STEPPER_SAVE_DELAY_MS,
  TYPING_SAVE_DELAY_MS,
  createRoomSettingsSaver,
} from "../src/lib/roomSettingsAutosave.ts";

function createEnvironment() {
  const timers = new Map();
  let nextId = 1;
  const environment = {
    sent: [],
    statuses: [],
    rejections: [],
    /** Resolvers for the acknowledgement of each sent patch, in order. */
    acks: [],
    send(patch) {
      environment.sent.push(patch);
      return new Promise((resolve, reject) => {
        environment.acks.push({ resolve, reject });
      });
    },
    onStatus(status) {
      environment.statuses.push(status);
    },
    onRejected(message) {
      environment.rejections.push(message);
    },
    setTimeout(handler, delayMs) {
      const id = nextId++;
      timers.set(id, { handler, delayMs });
      return id;
    },
    clearTimeout(timeoutId) {
      timers.delete(timeoutId);
    },
    armedDelays() {
      return [...timers.values()].map((timer) => timer.delayMs);
    },
    /** Run every armed timer, as the browser would once the delay elapses. */
    elapse() {
      const armed = [...timers.values()];
      timers.clear();
      for (const timer of armed) timer.handler();
    },
    /** Answer the oldest unanswered send. */
    ack(response = { ok: true }) {
      environment.acks.shift().resolve(response);
      return new Promise((resolve) => setImmediate(resolve));
    },
    fail(error = new Error("disconnected")) {
      environment.acks.shift().reject(error);
      return new Promise((resolve) => setImmediate(resolve));
    },
  };
  return environment;
}

test("changes made inside the window go out as one merged patch", () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4 });
  saver.queue({ scoringMode: "none" });
  saver.queue({ rounds: 5 });
  assert.deepEqual(environment.sent, []);

  environment.elapse();
  assert.deepEqual(environment.sent, [{ rounds: 5, scoringMode: "none" }]);
});

test("the shortest delay asked for wins, so a toggle is not held back by typing", () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ name: "Studio" }, TYPING_SAVE_DELAY_MS);
  saver.queue({ rounds: 4 }, STEPPER_SAVE_DELAY_MS);
  assert.deepEqual(environment.armedDelays(), [STEPPER_SAVE_DELAY_MS]);

  saver.queue({ isPublic: false });
  assert.deepEqual(environment.armedDelays(), [0], "a switch goes out on the next tick");
});

test("a change made mid-flight is not lost and never overlaps the request", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4 });
  environment.elapse();
  assert.equal(environment.sent.length, 1);

  saver.queue({ rounds: 6 });
  environment.elapse();
  assert.equal(environment.sent.length, 1, "a second request must wait for the first");

  await environment.ack();
  assert.deepEqual(environment.sent, [{ rounds: 4 }, { rounds: 6 }]);
});

test("a refusal is reported once and the patch is dropped, not retried", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ maxPlayers: 2 });
  environment.elapse();
  await environment.ack({ ok: false, error: "Max players cannot be below the 4 players already in the room" });

  assert.deepEqual(environment.rejections, [
    "Max players cannot be below the 4 players already in the room",
  ]);
  environment.elapse();
  assert.equal(environment.sent.length, 1, "a refused patch is not retried");
});

test("a dropped connection keeps the patch, and flush sends it again", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4 });
  environment.elapse();
  await environment.fail();

  assert.deepEqual(environment.rejections, [], "the value was fine, the connection was not");
  assert.equal(environment.statuses.at(-1), "failed");

  saver.flush();
  assert.deepEqual(environment.sent, [{ rounds: 4 }, { rounds: 4 }]);
});

test("an edit made while offline wins over the patch that failed to send", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4, name: "Studio" });
  environment.elapse();
  saver.queue({ rounds: 7 });
  await environment.fail();

  saver.flush();
  assert.deepEqual(environment.sent.at(-1), { rounds: 7, name: "Studio" });
});

test("status runs pending, saving, saved, then goes quiet", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4 });
  environment.elapse();
  await environment.ack();
  assert.deepEqual(environment.statuses, ["pending", "saving", "saved"]);

  assert.deepEqual(environment.armedDelays(), [SAVED_STATUS_MS]);
  environment.elapse();
  assert.equal(environment.statuses.at(-1), "idle");
});

test("flush sends without waiting out the timer", () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ customPrompts: "apple\nbanana", customPromptsOnly: true }, TYPING_SAVE_DELAY_MS);
  saver.flush();

  assert.deepEqual(environment.sent, [{ customPrompts: "apple\nbanana", customPromptsOnly: true }]);
  assert.deepEqual(environment.armedDelays(), [], "the debounce timer is disarmed");
});

test("flush with nothing pending sends nothing", () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.flush();
  assert.deepEqual(environment.sent, []);
});

test("a request outstanding at teardown cannot report into the torn-down form", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4 });
  environment.elapse();
  saver.reset();
  await environment.ack({ ok: false, error: "Only the host can change room settings" });

  assert.deepEqual(environment.rejections, []);
});
