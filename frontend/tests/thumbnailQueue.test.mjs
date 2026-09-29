import assert from "node:assert/strict";
import test from "node:test";

import { ThumbnailCancelled, ThumbnailDropped, createThumbnailQueue } from "../src/lib/thumbnailQueue.ts";

/** A worker the test answers by hand; what it was sent crosses as a real
    message would, transferred buffers detached. */
class FakeWorker {
  constructor() {
    this.sent = [];
    this.terminated = false;
    this.onmessage = null;
    this.onerror = null;
  }
  postMessage(message, transfer) {
    this.sent.push(structuredClone(message, { transfer }));
  }
  answer(index = this.sent.length - 1, png = new Uint8Array([7, 7]).buffer) {
    const { id } = this.sent[index];
    this.onmessage({ data: png === null ? { id, png: null } : { id, png, width: 10, height: 8 } });
  }
  terminate() {
    this.terminated = true;
  }
}

const bytes = (value) => new Uint8Array([value, value, value]).buffer;
const tick = () => new Promise((resolve) => setImmediate(resolve));

function queueWith(overrides = {}) {
  const workers = [];
  const onPage = [];
  const queue = createThumbnailQueue({
    createWorker: () => {
      const worker = new FakeWorker();
      workers.push(worker);
      return worker;
    },
    renderOnPage: async (payload, width) => {
      onPage.push({ payload, width });
      return { png: new Uint8Array([1]), width, height: 1 };
    },
    idleMs: 0,
    ...overrides,
  });
  return { queue, workers, onPage };
}

test("one job at a time goes to the one worker, in order", async () => {
  const { queue, workers } = queueWith();
  const first = queue.draw(bytes(1), 100);
  const second = queue.draw(bytes(2), 200);
  assert.equal(workers.length, 1);
  assert.equal(workers[0].sent.length, 1, "the second waits for the first");
  assert.deepEqual(queue.load(), { pending: 1, running: true, worker: true });
  workers[0].answer();
  assert.deepEqual(await first, { png: new Uint8Array([7, 7]), width: 10, height: 8 });
  assert.equal(workers[0].sent.length, 2);
  assert.equal(workers[0].sent[1].pixelWidth, 200);
  workers[0].answer();
  await second;
  assert.deepEqual(queue.load(), { pending: 0, running: false, worker: true });
});

test("the caller's bytes are copied, never transferred away", async () => {
  const { queue, workers } = queueWith();
  const own = bytes(3);
  const drawn = queue.draw(own, 100);
  assert.equal(own.byteLength, 3);
  assert.deepEqual([...new Uint8Array(workers[0].sent[0].bytes)], [3, 3, 3]);
  workers[0].answer();
  await drawn;
});

test("a cancelled job still waiting is never sent", async () => {
  const { queue, workers } = queueWith();
  const first = queue.draw(bytes(1), 100);
  const abort = new AbortController();
  const second = queue.draw(bytes(2), 100, abort.signal);
  abort.abort();
  await assert.rejects(second, ThumbnailCancelled);
  workers[0].answer();
  await first;
  assert.equal(workers[0].sent.length, 1);
  assert.deepEqual(queue.load(), { pending: 0, running: false, worker: true });
});

test("a cancelled job being drawn is thrown away, and the next one goes", async () => {
  const { queue, workers } = queueWith();
  const abort = new AbortController();
  const first = queue.draw(bytes(1), 100, abort.signal);
  const second = queue.draw(bytes(2), 100);
  abort.abort();
  workers[0].answer(0);
  await assert.rejects(first, ThumbnailCancelled);
  assert.equal(workers[0].sent.length, 2);
  workers[0].answer(1);
  await second;
});

test("an answer for a job that is not the one being drawn is ignored", async () => {
  const { queue, workers } = queueWith();
  const drawn = queue.draw(bytes(1), 100);
  workers[0].onmessage({ data: { id: 999, png: null } });
  assert.equal(queue.load().running, true);
  workers[0].answer();
  assert.ok(await drawn);
});

test("past the cap the oldest waiting job is dropped, not the newest", async () => {
  const { queue, workers } = queueWith({ maxPending: 2 });
  const running = queue.draw(bytes(1), 100);
  const oldest = queue.draw(bytes(2), 100);
  const middle = queue.draw(bytes(3), 100);
  const newest = queue.draw(bytes(4), 100);
  await assert.rejects(oldest, ThumbnailDropped);
  assert.equal(queue.load().pending, 2);
  for (let index = 0; index < 3; index++) {
    workers[0].answer(index);
    await tick();
  }
  await Promise.all([running, middle, newest]);
  // Newest first: the card a scroll just brought in before one it passed.
  assert.deepEqual(workers[0].sent.map((job) => new Uint8Array(job.bytes)[0]), [1, 4, 3]);
});

test("an undecodable history comes back as no image", async () => {
  const { queue, workers } = queueWith();
  const drawn = queue.draw(bytes(1), 100);
  workers[0].answer(0, null);
  assert.equal(await drawn, null);
});

test("with no worker to be had, thumbnails are drawn on the page", async () => {
  const onPage = [];
  const queue = createThumbnailQueue({
    renderOnPage: async (payload, width) => {
      onPage.push(width);
      return { png: new Uint8Array([1]), width, height: 1 };
    },
  });
  assert.ok(await queue.draw(bytes(1), 64));
  assert.deepEqual(onPage, [64]);

  const throwing = queueWith({ createWorker: () => { throw new Error("CSP"); } });
  assert.ok(await throwing.queue.draw(bytes(1), 80));
  assert.deepEqual(throwing.onPage.map((job) => job.width), [80]);
});

test("a worker that dies hands its job, and every later one, to the page", async () => {
  const { queue, workers, onPage } = queueWith();
  const first = queue.draw(bytes(1), 100);
  workers[0].onerror(new Error("chunk failed to load"));
  assert.ok(await first);
  assert.equal(workers[0].terminated, true);
  assert.ok(await queue.draw(bytes(2), 120));
  assert.equal(workers.length, 1, "not started again");
  assert.deepEqual(onPage.map((job) => job.width), [100, 120]);
});

test("an idle worker is let go, and a new one started for the next card", async () => {
  const { queue, workers } = queueWith({ idleMs: 5 });
  const drawn = queue.draw(bytes(1), 100);
  workers[0].answer();
  await drawn;
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(workers[0].terminated, true);
  assert.equal(queue.load().worker, false);
  const again = queue.draw(bytes(2), 100);
  assert.equal(workers.length, 2);
  workers[1].answer();
  await again;
});

test("an already-cancelled request is refused at once", async () => {
  const { queue, workers } = queueWith();
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(queue.draw(bytes(1), 100, abort.signal), ThumbnailCancelled);
  assert.equal(workers.length, 0);
});

test("the newest card waiting is drawn next", async () => {
  const { queue, workers } = queueWith();
  const drawn = [queue.draw(bytes(1), 100), queue.draw(bytes(2), 100), queue.draw(bytes(3), 100)];
  for (let index = 0; index < 3; index++) {
    workers[0].answer(index);
    await tick();
  }
  await Promise.all(drawn);
  assert.deepEqual(workers[0].sent.map((job) => new Uint8Array(job.bytes)[0]), [1, 3, 2]);
});

test("a cancelled job is not drawn on the page when its worker dies", async () => {
  const { queue, workers, onPage } = queueWith();
  const abort = new AbortController();
  const gone = queue.draw(bytes(1), 100, abort.signal);
  abort.abort();
  workers[0].onerror(new Error("worker died"));
  await assert.rejects(gone, ThumbnailCancelled);
  assert.deepEqual(onPage, [], "nobody wanted that picture");
});
