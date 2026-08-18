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
    preview: async () => ({ ok: true, room }),
    join: async () => sessionResponse,
    saveNickname: () => {},
    acceptSession: () => {},
    requestErrorMessage: (_error, action) => `Could not ${action}.`,
    ...overrides,
  };
}

test("direct player and spectator joins preserve their distinct modes", async () => {
  const joins = [];
  const nicknames = [];
  const accepted = [];
  const deps = dependencies({
    join: async (request) => {
      joins.push(request);
      return sessionResponse;
    },
    saveNickname: (nickname) => nicknames.push(nickname),
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
  assert.deepEqual(nicknames, ["Ada", "Grace"]);
  assert.deepEqual(accepted, [
    { roomId: "room-1", code: "ABC123", playerId: "player-1" },
    { roomId: "room-1", code: "ABC123", playerId: "player-1" },
  ]);
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

test("a late response cannot overwrite the newest preview", async () => {
  const first = deferred();
  const second = deferred();
  let calls = 0;
  const machine = new RoomEntryMachine("ABC123", "Ada", dependencies({
    preview: () => {
      calls += 1;
      return calls === 1 ? first.promise : second.promise;
    },
  }));

  const firstLoad = machine.load();
  const secondLoad = machine.load();
  const newestRoom = { ...room, name: "Newest room state" };
  second.resolve({ ok: true, room: newestRoom });
  await secondLoad;
  first.resolve({ ok: false, error: "stale failure" });
  await firstLoad;

  assert.deepEqual(machine.getSnapshot().state, { status: "preview", room: newestRoom, notice: undefined });
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
