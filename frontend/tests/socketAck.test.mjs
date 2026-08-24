import assert from "node:assert/strict";
import test from "node:test";

import { SocketRequestError, emitWithAckOn } from "../src/lib/socket.ts";

function fakeSocket({ connected = true } = {}) {
  const listeners = new Map();
  return {
    connected,
    emitted: [],
    on(event, listener) {
      listeners.set(event, [...(listeners.get(event) ?? []), listener]);
    },
    off(event, listener) {
      listeners.set(event, (listeners.get(event) ?? []).filter((l) => l !== listener));
    },
    emit(event, data, ack) {
      this.emitted.push({ event, data, ack });
    },
    listenerCount(event) {
      return (listeners.get(event) ?? []).length;
    },
    drop() {
      this.connected = false;
      for (const listener of [...(listeners.get("disconnect") ?? [])]) listener();
    },
    restore() {
      this.connected = true;
      for (const listener of [...(listeners.get("connect") ?? [])]) listener();
    },
  };
}

test("a disconnected socket is never handed the packet to queue", async () => {
  const socket = fakeSocket({ connected: false });

  const error = await emitWithAckOn(socket, "create_room", { name: "Room" }, { timeoutMs: 1 }).catch((e) => e);

  assert.ok(error instanceof SocketRequestError);
  assert.deepEqual(socket.emitted, [], "the packet was queued for delivery on reconnect");
});

test("a request made before the first handshake is sent once it lands", async () => {
  const socket = fakeSocket({ connected: false });

  const pending = emitWithAckOn(socket, "create_room", { name: "Room" });
  assert.deepEqual(socket.emitted, []);

  socket.restore();
  assert.equal(socket.emitted.length, 1, "the request was dropped rather than waiting");
  socket.emitted[0].ack({ ok: true, roomId: "r1" });

  assert.deepEqual(await pending, { ok: true, roomId: "r1" });
});

test("a request that times out before connecting leaves nothing to deliver", async () => {
  const socket = fakeSocket({ connected: false });

  const error = await emitWithAckOn(socket, "start_game", null, { timeoutMs: 1 }).catch((e) => e);
  assert.equal(error.code, "timeout");

  socket.restore();
  assert.deepEqual(socket.emitted, [], "a late connection replayed the abandoned action");
  assert.equal(socket.listenerCount("connect"), 0);
  assert.equal(socket.listenerCount("disconnect"), 0);
});

test("a connected socket emits and resolves with the acknowledgement", async () => {
  const socket = fakeSocket();

  const pending = emitWithAckOn(socket, "join_room", { code: "ABC123" });
  assert.equal(socket.emitted.length, 1);
  socket.emitted[0].ack({ ok: true });

  assert.deepEqual(await pending, { ok: true });
  assert.equal(socket.listenerCount("disconnect"), 0, "the listener outlived the request");
});

test("a socket that drops mid-flight rejects once, as disconnected", async () => {
  const socket = fakeSocket();

  const pending = emitWithAckOn(socket, "start_game", null);
  socket.drop();
  const error = await pending.catch((e) => e);

  assert.equal(error.code, "disconnected");
  // A late acknowledgement must not resolve a promise already rejected.
  socket.emitted[0].ack({ ok: true });
  assert.equal(await pending.then(() => "resolved", () => "rejected"), "rejected");
});

test("a silent server still times out", async () => {
  const socket = fakeSocket();

  const error = await emitWithAckOn(socket, "start_game", null, { timeoutMs: 1 }).catch((e) => e);

  assert.equal(error.code, "timeout");
  assert.equal(socket.listenerCount("disconnect"), 0);
});
