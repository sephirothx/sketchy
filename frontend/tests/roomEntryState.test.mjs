import assert from "node:assert/strict";
import test from "node:test";

import { RoomEntryMachine } from "../src/lib/roomEntryState.ts";

const room = {
  id: "room-1",
  code: "ABC123",
  name: "Test room",
  isPublic: false,
  playerCount: 2,
  spectatorCount: 0,
  maxPlayers: 8,
  isFull: false,
  rounds: 3,
  customWordCount: 0,
  customWordsOnly: false,
  drawingSeconds: 90,
  hintMode: "checkpoints",
  scoringMode: "default",
  spectatorsSeeSolution: false,
  hideMaskedPrompt: false,
  state: "waiting",
};

const sessionResponse = {
  ok: true,
  roomId: "room-1",
  code: "ABC123",
  playerId: "player-1",
};

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function dependencies(overrides = {}) {
  return {
    reconnect: async () => ({ ok: false }),
    preview: async () => ({ ok: true, room }),
    join: async () => sessionResponse,
    acceptSession: () => {},
    requestErrorMessage: (_error, action) => `Could not ${action}.`,
    ...overrides,
  };
}

test("an existing seat is resumed without loading a preview", async () => {
  const accepted = [];
  let previewCalls = 0;
  const machine = new RoomEntryMachine("ABC123", "Ada", dependencies({
    reconnect: async () => sessionResponse,
    preview: async () => {
      previewCalls += 1;
      return { ok: true, room };
    },
    acceptSession: (session) => accepted.push(session),
  }));

  await machine.load();
  assert.deepEqual(accepted, [{
    roomId: "room-1",
    code: "ABC123",
    playerId: "player-1",
  }]);
  assert.equal(previewCalls, 0);
});

test("a visitor with no seat sees the preview and is never auto-joined", async () => {
  const accepted = [];
  const machine = new RoomEntryMachine("ABC123", "Ada", dependencies({
    reconnect: async () => ({ ok: false, error: "No existing session in this room" }),
    acceptSession: (session) => accepted.push(session),
  }));

  await machine.load();
  assert.deepEqual(accepted, []);
  assert.deepEqual(machine.getSnapshot().state, { status: "preview", room });
});

test("a nickname breaking the shared name rule is rejected before joining", async () => {
  const joins = [];
  const machine = new RoomEntryMachine("ABC123", "Ada", dependencies({
    join: async (request) => { joins.push(request); return sessionResponse; },
  }));
  await machine.load();

  for (const bad of ["ab", "has space", "Guest", "way-too-long-a-nickname"]) {
    machine.setNicknameInput(bad);
    await machine.join("player");
    assert.equal(joins.length, 0, bad);
    assert.ok(machine.getSnapshot().state.error, bad);
  }

  machine.setNicknameInput("Ada-Lovelace");
  await machine.join("player");
  assert.equal(joins.length, 1);
});

test("direct player and spectator joins preserve their distinct modes", async () => {
  const joins = [];
  const accepted = [];
  const deps = dependencies({
    join: async (request) => {
      joins.push(request);
      return sessionResponse;
    },
    acceptSession: (session) => accepted.push(session),
  });

  const player = new RoomEntryMachine("ABC123", " Ada ", deps);
  await player.load();
  await player.join("player");

  const spectator = new RoomEntryMachine("ABC123", "Grace", deps);
  await spectator.load();
  await spectator.join("spectator");

  assert.deepEqual(joins, [
    { code: "ABC123", nickname: "Ada", mode: "player" },
    { code: "ABC123", nickname: "Grace", mode: "spectator" },
  ]);
  assert.equal(accepted.length, 2);
});

test("disposing the machine ignores a pending response", async () => {
  const pending = deferred();
  const accepted = [];
  const machine = new RoomEntryMachine("ABC123", "Ada", dependencies({
    preview: () => pending.promise,
    acceptSession: (session) => accepted.push(session),
  }));
  const states = [];
  machine.subscribe((snapshot) => states.push(snapshot.state.status));

  const load = machine.load();
  machine.dispose();
  pending.resolve({ ok: true, room });
  await load;

  assert.deepEqual(states, ["loading", "loading"]);
  assert.deepEqual(accepted, []);
});

test("a superseded load cannot overwrite the newest preview", async () => {
  const probes = [];
  const newestRoom = { ...room, name: "Newest room state" };
  let previewCalls = 0;
  const machine = new RoomEntryMachine("ABC123", "Ada", dependencies({
    reconnect: () => {
      const pending = deferred();
      probes.push(pending);
      return pending.promise;
    },
    preview: async () => {
      previewCalls += 1;
      return { ok: true, room: newestRoom };
    },
  }));

  const firstLoad = machine.load();
  const secondLoad = machine.load();
  assert.equal(probes.length, 2);

  // Newest load finishes first, then the stale one comes back late.
  probes[1].resolve({ ok: false });
  await secondLoad;
  probes[0].resolve({ ok: false });
  await firstLoad;

  assert.deepEqual(machine.getSnapshot().state, { status: "preview", room: newestRoom });
  // The superseded load is abandoned at the resume probe, so it never even
  // asks for a preview it would not be allowed to publish.
  assert.equal(previewCalls, 1);
});

test("a room-full player response returns to preview while keeping spectator join available", async () => {
  const machine = new RoomEntryMachine("ABC123", "Ada", dependencies({
    join: async () => ({ ok: false, error: "Room is full" }),
  }));

  await machine.load();
  await machine.join("player");

  assert.equal(machine.getSnapshot().state.status, "preview");
  assert.equal(machine.getSnapshot().state.room.isFull, true);
  assert.equal(
    machine.getSnapshot().state.error,
    "The player slots just filled up, but you can still spectate.",
  );
});
