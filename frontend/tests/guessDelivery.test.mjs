import assert from "node:assert/strict";
import test from "node:test";

import { GUESS_ACK_TIMEOUT_MS, createGuessSender } from "../src/lib/socket.ts";

/** A socket that records volatile emits and lets the test settle each one. */
function fakeSocket({ connected = true, scope = { connection: "c1", code: "ROOM01", turnId: "turn-1" } } = {}) {
  return {
    connected,
    current: scope,
    scope() {
      return this.connected ? this.current : null;
    },
    sent: [],
    emitTransient(event, data, timeoutMs, ack) {
      this.sent.push({ event, data, timeoutMs, ack });
    },
    /** The server acknowledged the nth attempt. */
    acknowledge(index = this.sent.length - 1) {
      this.sent[index].ack(undefined);
    },
    /** The nth attempt went unacknowledged for the whole timeout. */
    timeOut(index = this.sent.length - 1) {
      this.sent[index].ack(new Error("operation has timed out"));
    },
  };
}

test("an acknowledged guess is sent once, with an id the server can dedupe on", () => {
  const socket = fakeSocket();
  const sendGuess = createGuessSender(socket);
  let delivered = 0;
  let undelivered = 0;

  sendGuess("panda", { onDelivered: () => delivered++, onUndelivered: () => undelivered++ });
  assert.equal(socket.sent.length, 1);
  assert.equal(socket.sent[0].event, "guess");
  assert.equal(socket.sent[0].data.text, "panda");
  assert.equal(typeof socket.sent[0].data.id, "number");
  assert.equal(socket.sent[0].timeoutMs, GUESS_ACK_TIMEOUT_MS);

  socket.acknowledge();
  assert.equal(delivered, 1);
  assert.equal(undelivered, 0);
  assert.equal(socket.sent.length, 1, "an acknowledged guess was resent anyway");
});

test("a guess the server never acknowledges is resent once, with the same id", () => {
  const socket = fakeSocket();
  const sendGuess = createGuessSender(socket);
  let undelivered = 0;

  sendGuess("panda", { onUndelivered: () => undelivered++ });
  socket.timeOut();

  assert.equal(socket.sent.length, 2, "the dropped guess was not resent");
  assert.deepEqual(socket.sent[1].data, socket.sent[0].data);
  assert.equal(undelivered, 0, "reported as lost while a retry was still in flight");

  socket.acknowledge();
  assert.equal(socket.sent.length, 2, "the retry was retried");
});

test("a guess whose retry is also unacknowledged is reported as lost", () => {
  const socket = fakeSocket();
  const sendGuess = createGuessSender(socket);
  let undelivered = 0;

  sendGuess("panda", { onUndelivered: () => undelivered++ });
  socket.timeOut();
  socket.timeOut();

  assert.equal(socket.sent.length, 2, "retried more than once");
  assert.equal(undelivered, 1);
});

test("a guess is not resent while disconnected, because the ids start over", () => {
  const socket = fakeSocket();
  const sendGuess = createGuessSender(socket);
  let undelivered = 0;

  sendGuess("panda", { onUndelivered: () => undelivered++ });
  socket.connected = false;
  socket.timeOut();

  assert.equal(socket.sent.length, 1, "a guess was replayed into a turn that may have ended");
  assert.equal(undelivered, 1);
});

test("each guess gets its own id, so a retry is never mistaken for the next guess", () => {
  const socket = fakeSocket();
  const sendGuess = createGuessSender(socket);

  sendGuess("panda");
  socket.acknowledge();
  sendGuess("pandas");
  socket.acknowledge();
  sendGuess("bear");
  socket.acknowledge();

  const ids = socket.sent.map((attempt) => attempt.data.id);
  assert.equal(new Set(ids).size, ids.length, `ids repeated: ${ids.join(", ")}`);
});

test("a slow acknowledgement arriving after the retry does not report a loss", () => {
  const socket = fakeSocket();
  const sendGuess = createGuessSender(socket);
  let delivered = 0;
  let undelivered = 0;

  sendGuess("panda", { onDelivered: () => delivered++, onUndelivered: () => undelivered++ });
  socket.timeOut();
  socket.acknowledge(1);

  assert.equal(delivered, 1);
  assert.equal(undelivered, 0);
});

test("a guess carries the room and turn it was made in", () => {
  const socket = fakeSocket();
  createGuessSender(socket)("cat");
  assert.deepEqual(socket.sent[0].data, { text: "cat", id: 0, code: "ROOM01", turnId: "turn-1" });
});

test("a connection replaced before the timeout gets no retry, even though the socket is connected", () => {
  const socket = fakeSocket();
  const outcomes = [];
  createGuessSender(socket)("cat", { onDelivered: () => outcomes.push("delivered"), onUndelivered: () => outcomes.push("lost") });
  socket.current = { ...socket.current, connection: "c2" };
  socket.timeOut();
  assert.equal(socket.sent.length, 1, "the retry would land on another connection");
  assert.deepEqual(outcomes, ["lost"]);
});

test("a room switched on the same socket, or a turn that ended, cancels the retry", () => {
  for (const change of [{ code: "OTHER1" }, { turnId: "turn-2" }]) {
    const socket = fakeSocket();
    const outcomes = [];
    createGuessSender(socket)("cat", { onUndelivered: () => outcomes.push("lost") });
    socket.current = { ...socket.current, ...change };
    socket.timeOut();
    assert.equal(socket.sent.length, 1, JSON.stringify(change));
    assert.deepEqual(outcomes, ["lost"]);
  }
});

test("a dropped first packet is retried inside the same scope with the same id and scope", () => {
  const socket = fakeSocket();
  createGuessSender(socket)("cat");
  socket.timeOut(0);
  assert.equal(socket.sent.length, 2);
  assert.deepEqual(socket.sent[1].data, socket.sent[0].data);
});

test("with no place to belong to, a guess is reported lost without being sent", () => {
  const socket = fakeSocket({ scope: null });
  const outcomes = [];
  createGuessSender(socket)("cat", { onUndelivered: () => outcomes.push("lost") });
  assert.equal(socket.sent.length, 0);
  assert.deepEqual(outcomes, ["lost"]);
});

test("each result settles exactly once, whatever arrives late", () => {
  const socket = fakeSocket();
  const outcomes = [];
  createGuessSender(socket)("cat", { onDelivered: () => outcomes.push("delivered"), onUndelivered: () => outcomes.push("lost") });
  socket.timeOut(0);
  socket.acknowledge(1);
  socket.acknowledge(0); // the first attempt's ack, arriving after all
  socket.timeOut(1);
  assert.deepEqual(outcomes, ["delivered"]);

  const lost = fakeSocket();
  const late = [];
  createGuessSender(lost)("dog", { onDelivered: () => late.push("delivered"), onUndelivered: () => late.push("lost") });
  lost.timeOut(0);
  lost.timeOut(1);
  lost.acknowledge(0);
  assert.deepEqual(late, ["lost"]);
});
