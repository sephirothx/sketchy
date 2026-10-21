import assert from "node:assert/strict";
import test from "node:test";

import {
  PAGE_LAYER_KEY,
  createPageHistory,
  layerDepth,
  layerState,
  planLayerPop,
  planLayers,
} from "../src/lib/pageHistory.ts";
import { historyPortFor } from "../src/lib/roomHistory.ts";

const PROFILE = "/profile";

/** A browser's session history, as far as a page can see it: `go` queues and
`settle()` lands each traversal with a `popstate`, a traversal past either end
is dropped, and `navigate` is the router's push. As `roomHistory.test.mjs`'s. */
class FakeWindow {
  constructor(path = PROFILE) {
    this.entries = [{ path, state: { usr: null, key: "start", idx: 0 } }];
    this.index = 0;
    this.queue = [];
    this.listeners = [];
    const self = this;
    this.history = {
      get state() {
        return self.entries[self.index].state;
      },
      pushState(state) {
        self.entries.splice(self.index + 1);
        self.entries.push({ path: self.entries[self.index].path, state });
        self.index += 1;
      },
      go(delta) {
        self.queue.push(delta);
      },
    };
    this.location = {
      get pathname() {
        return self.entries[self.index].path;
      },
    };
  }

  addEventListener(type, listener) {
    assert.equal(type, "popstate");
    this.listeners.push(listener);
  }

  setTimeout() {
    return 0;
  }

  clearTimeout() {}

  queueMicrotask(task) {
    queueMicrotask(task);
  }

  navigate(path) {
    const idx = (this.history.state?.idx ?? 0) + 1;
    this.entries.splice(this.index + 1);
    this.entries.push({ path, state: { usr: null, key: `k${this.entries.length}`, idx } });
    this.index += 1;
  }

  press(delta) {
    this.queue.push(delta);
  }

  async settle() {
    for (;;) {
      await new Promise((resolve) => setImmediate(resolve));
      const delta = this.queue.shift();
      if (delta === undefined) return;
      const target = this.index + delta;
      if (target < 0 || target >= this.entries.length) continue;
      this.index = target;
      for (const listener of [...this.listeners]) listener();
    }
  }

  depth() {
    return layerDepth(this.history.state, this.location.pathname);
  }
}

function setup(path = PROFILE) {
  const win = new FakeWindow(path);
  const page = createPageHistory(historyPortFor(win));
  return { win, page };
}

test("a layer entry keeps the router's keys, moves its index on, and names its page", () => {
  const state = layerState({ usr: { from: "x" }, key: "abc", idx: 4 }, PROFILE, 1);
  assert.deepEqual(state, { usr: { from: "x" }, key: "abc", idx: 5, [PAGE_LAYER_KEY]: { path: PROFILE, depth: 1 } });
  assert.equal(layerDepth(state, PROFILE), 1);
  // Another page's mark, or none, is the page itself.
  assert.equal(layerDepth(state, "/gallery"), 0);
  assert.equal(layerDepth({ idx: 2 }, PROFILE), 0);
  assert.equal(layerDepth({ [PAGE_LAYER_KEY]: { path: PROFILE, depth: 0 } }, PROFILE), 0);
});

test("the plans: push up to what is open, go down to it, close what Back passed", () => {
  assert.deepEqual(planLayers(0, 2), { push: [1, 2] });
  assert.deepEqual(planLayers(2, 0), { go: -2 });
  assert.equal(planLayers(1, 1), null);
  assert.deepEqual(planLayerPop(0, 1, false), { kind: "close", count: 1 });
  assert.deepEqual(planLayerPop(2, 0, false), { kind: "go", delta: -2 });
  assert.deepEqual(planLayerPop(1, 1, false), { kind: "none" });
  assert.deepEqual(planLayerPop(0, 1, true), { kind: "reconcile" });
});

test("Back closes a layer and leaves the page where it was", async () => {
  const { win, page } = setup();
  let closed = 0;
  page.open(() => (closed += 1));
  await win.settle();
  assert.equal(win.entries.length, 2);
  assert.equal(win.depth(), 1);
  assert.equal(win.location.pathname, PROFILE);

  win.press(-1);
  await win.settle();
  assert.equal(closed, 1);
  assert.equal(win.index, 0);
  assert.equal(win.location.pathname, PROFILE);
});

test("a layer closed by its own control takes its entry back", async () => {
  const { win, page } = setup();
  let closed = 0;
  const release = page.open(() => (closed += 1));
  await win.settle();
  release();
  await win.settle();
  assert.equal(closed, 0, "closing it is not Back");
  assert.equal(win.index, 0);
  assert.equal(win.depth(), 0);
  // Back now leaves the page, as it did before the layer opened.
  release();
  await win.settle();
  assert.equal(win.index, 0);
});

test("two layers: Back closes the top one, and again the one under it", async () => {
  const { win, page } = setup();
  const closed = [];
  page.open(() => closed.push("viewer"));
  page.open(() => closed.push("overview"));
  await win.settle();
  assert.equal(win.depth(), 2);

  win.press(-1);
  await win.settle();
  assert.deepEqual(closed, ["overview"]);
  assert.equal(win.depth(), 1);

  win.press(-1);
  await win.settle();
  assert.deepEqual(closed, ["overview", "viewer"]);
  assert.equal(win.depth(), 0);
});

test("closing both at once takes both entries back in one step", async () => {
  const { win, page } = setup();
  const releaseViewer = page.open(() => {});
  const releaseOverview = page.open(() => {});
  await win.settle();
  releaseViewer();
  releaseOverview();
  await win.settle();
  assert.equal(win.index, 0);
});

test("opening and closing in one go costs the history nothing", async () => {
  const { win, page } = setup();
  const release = page.open(() => {});
  release();
  await win.settle();
  assert.equal(win.entries.length, 1);
});

test("a layer left open on the way to another page is stepped over by Back", async () => {
  const { win, page } = setup();
  const release = page.open(() => {});
  await win.settle();
  // A link followed from under the layer: the router pushes, the layer goes.
  win.navigate("/gallery");
  release();
  await win.settle();
  assert.equal(win.location.pathname, "/gallery");
  assert.equal(win.entries.length, 3, "nothing is taken back from another page");

  // Back from there lands on the layer's entry, which has nothing open: it
  // carries on to the page under it.
  win.press(-1);
  await win.settle();
  assert.equal(win.location.pathname, PROFILE);
  assert.equal(win.index, 0);
});
