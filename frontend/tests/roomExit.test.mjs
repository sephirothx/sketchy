import assert from "node:assert/strict";
import test from "node:test";

import { selectRoomRoute, useGameStore } from "../src/store/gameStore.ts";

// What `/room/:code` draws while a room is being left. The exit used to be a
// bare flag that only the lobby's mount cleared, and an invitation's Join
// navigates on to the friend's room as soon as its answer arrives: when that
// overtook the lobby before it mounted, the flag stayed up and the friend's
// room drew nothing at all.

function seatIn(code) {
  useGameStore.getState().setSession({ roomId: `id-${code}`, code, playerId: `p-${code}` });
}

// ActiveGameRoom.exitRoom, in its order.
function leave(code) {
  const store = useGameStore.getState();
  store.setExitingRoom(code);
  store.clearSession();
  store.reset();
}

function route(code) {
  return selectRoomRoute(useGameStore.getState(), code);
}

function fresh() {
  const store = useGameStore.getState();
  store.reset();
  store.setExitingRoom(null);
}

test("the room being left draws nothing, not its invite screen", () => {
  fresh();
  seatIn("AAAAAA");
  assert.equal(route("AAAAAA"), "room");
  leave("AAAAAA");
  assert.equal(route("AAAAAA"), "leaving");
  assert.equal(route("aaaaaa"), "leaving", "whatever the case of the URL");
});

test("a friend's room entered before the lobby mounted still draws", () => {
  fresh();
  seatIn("AAAAAA");
  leave("AAAAAA");
  // The join's answer arrives while the left room's route is still on screen.
  seatIn("BBBBBB");
  assert.equal(route("BBBBBB"), "room");
  // ...and that route must not become the invite screen for the frame before
  // the navigation to the friend's room commits: it would ask the server to
  // reconnect the seat just given up.
  assert.equal(route("AAAAAA"), "leaving");
});

test("the lobby ends the exit, and the left room is an ordinary address again", () => {
  fresh();
  seatIn("AAAAAA");
  leave("AAAAAA");
  useGameStore.getState().setExitingRoom(null);
  assert.equal(route("AAAAAA"), "invite");
});

test("a seat taken again in the room being left ends the exit", () => {
  fresh();
  seatIn("AAAAAA");
  leave("AAAAAA");
  seatIn("aaaaaa");
  assert.equal(useGameStore.getState().exitingRoomCode, null);
  assert.equal(route("AAAAAA"), "room");
});

test("the reset on the way out keeps the exit", () => {
  fresh();
  useGameStore.getState().setExitingRoom("AAAAAA");
  useGameStore.getState().reset();
  assert.equal(useGameStore.getState().exitingRoomCode, "AAAAAA");
});

test("a session for another room never activates this route", () => {
  fresh();
  seatIn("BBBBBB");
  assert.equal(route("AAAAAA"), "invite");
});
