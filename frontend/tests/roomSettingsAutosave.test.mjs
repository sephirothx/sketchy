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

test("flush sends what is pending without waiting for the reply it is behind", () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4 });
  environment.elapse();
  assert.equal(environment.sent.length, 1);

  // The press that flushes is very often the press that starts the game, so
  // this patch has to be on the socket now, not after the first reply.
  saver.queue({ scoringMode: "none" });
  saver.flush();
  assert.deepEqual(environment.sent, [{ rounds: 4 }, { scoringMode: "none" }]);
});

test("a change made while a reply is outstanding still goes out", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4 });
  environment.elapse();
  saver.queue({ rounds: 6 });
  environment.elapse();

  await environment.ack();
  await environment.ack();
  assert.deepEqual(environment.sent, [{ rounds: 4 }, { rounds: 6 }]);
});

test("a reply for one change does not cut short another still waiting its turn", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ isPublic: false });
  environment.elapse();
  assert.equal(environment.sent.length, 1);

  saver.queue({ name: "S" }, TYPING_SAVE_DELAY_MS);
  await environment.ack();
  assert.equal(
    environment.sent.length,
    1,
    "the reply has nothing to do with the name the host is still typing",
  );

  environment.elapse();
  assert.deepEqual(environment.sent.at(-1), { name: "S" });
});

test("a reply that gets through takes the lost patch out with it", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ rounds: 4 });
  environment.elapse();
  saver.queue({ name: "Studio" });
  environment.elapse();

  await environment.fail();  // the rounds never made it
  await environment.ack();   // the name did, so the connection is back

  assert.deepEqual(environment.sent.at(-1), { rounds: 4 });
});

test("a retry cannot put an old value back over a newer one that got through", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ name: "Ab" });
  environment.elapse();
  saver.queue({ name: "Abc" });
  environment.elapse();
  assert.equal(environment.sent.length, 2);

  await environment.fail();  // the older send is the one the transport lost
  await environment.ack();   // the newer one landed

  saver.flush();
  assert.deepEqual(environment.sent.at(-1), { name: "Abc" });
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

test("a lost value is not put back under one the host has since retyped", async () => {
  const environment = createEnvironment();
  const saver = createRoomSettingsSaver(environment);

  saver.queue({ name: "A" }, TYPING_SAVE_DELAY_MS);
  environment.elapse();
  saver.queue({ isPublic: false });
  environment.elapse();

  await environment.fail();  // the name never made it
  saver.queue({ name: "AB" }, TYPING_SAVE_DELAY_MS);  // and is still being typed
  await environment.ack();   // the visibility did, so the lost patch is retried

  assert.equal(environment.sent.length, 2, "there is nothing left worth recovering");

  environment.elapse();
  assert.deepEqual(environment.sent.at(-1), { name: "AB" });
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
