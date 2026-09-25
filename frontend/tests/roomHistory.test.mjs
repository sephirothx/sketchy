import assert from "node:assert/strict";
import test from "node:test";

import {
  ROOM_ENTRY_KEY,
  createRoomHistory,
  exitStep,
  historyPortFor,
  isRoomPath,
  isSheetEntry,
  leaveRoomHistory,
  locate,
  planPop,
  planReconcile,
  pushedState,
} from "../src/lib/roomHistory.ts";

const CODE = "AB12CD";
const ROOM = `/room/${CODE}`;
/** The seat held in it; a rejoin holds another. */
const WHO = { code: CODE, seat: "seat-1" };

/** A browser's session history, as far as a room can see it.

`go` is asynchronous, as in a browser: traversals queue, and `settle()` lands
them one at a time, firing `popstate` for each. A traversal past either end of
the stack is dropped without an event, as a browser drops it. `navigate` is
what the router does - its own keys in the state, `idx` counted up. */
class FakeWindow {
  constructor() {
    this.entries = [{ path: "/", state: { usr: null, key: "lobby", idx: 0 } }];
    this.index = 0;
    this.queue = [];
    this.listeners = [];
    this.timers = new Map();
    this.nextTimer = 1;
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

  setTimeout(task) {
    const id = this.nextTimer++;
    this.timers.set(id, task);
    return id;
  }

  clearTimeout(id) {
    this.timers.delete(id);
  }

  queueMicrotask(task) {
    queueMicrotask(task);
  }

  navigate(path, usr = null, { replace = false } = {}) {
    const idx = (this.history.state?.idx ?? 0) + (replace ? 0 : 1);
    const entry = { path, state: { usr, key: `k${this.entries.length}`, idx } };
    if (replace) {
      this.entries[this.index] = entry;
      return;
    }
    this.entries.splice(this.index + 1);
    this.entries.push(entry);
    this.index += 1;
  }

  /** The user's Back or Forward: a traversal the port did not ask for. */
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

  async fireTimers() {
    const tasks = [...this.timers.values()];
    this.timers.clear();
    for (const task of tasks) task();
    await this.settle();
  }

  /** The stack as labels - `/room/AB12CD#1` for a room entry at depth 1 -
  with the current entry in brackets. */
  describe() {
    return this.entries
      .map((entry, index) => {
        const mark = entry.state?.[ROOM_ENTRY_KEY];
        const label = mark ? `${entry.path}#${mark.depth}` : entry.path;
        return index === this.index ? `[${label}]` : label;
      })
      .join(" ");
  }
}

/** A lobby, and a room entered from it, with the room's history started. */
async function enterRoom() {
  const win = new FakeWindow();
  win.navigate(ROOM);
  const port = historyPortFor(win);
  const room = createRoomHistory(port, WHO);
  const backs = [];
  room.onBackOnRoom(() => backs.push(win.describe()));
  room.start();
  await win.settle();
  return { win, port, room, backs };
}

/** A sheet as React holds one: Back closes it through its dismiss, which
unmounts it, which releases - the release then finding nothing to do. */
function openSheet(room, name) {
  const sheet = { name, open: true, dismissedByBack: false };
  sheet.release = room.open(() => {
    sheet.dismissedByBack = true;
    sheet.open = false;
    sheet.release();
  });
  sheet.close = () => {
    sheet.open = false;
    sheet.release();
  };
  return sheet;
}

// --- The rules, on their own --------------------------------------------

test("a room's path is recognised however the router spelled it", () => {
  assert.equal(isRoomPath("/room/AB12CD", CODE), true);
  assert.equal(isRoomPath("/room/ab12cd/", CODE), true);
  assert.equal(isRoomPath("/room/AB12CDE", CODE), false);
  assert.equal(isRoomPath("/settings/account", CODE), false);
});

test("an entry is the room's own only when it carries this seat's mark", () => {
  const mark = (code, depth, seat = WHO.seat) => ({ [ROOM_ENTRY_KEY]: { code, seat, depth } });
  assert.deepEqual(locate(mark(CODE, 2), ROOM, WHO), { kind: "entry", depth: 2 });
  assert.deepEqual(locate(mark("ab12cd", 0), ROOM, WHO), { kind: "entry", depth: 0 });
  assert.deepEqual(locate({ usr: null, key: "a", idx: 3 }, ROOM, WHO), { kind: "base" });
  assert.deepEqual(locate(null, ROOM, WHO), { kind: "base" });
  // Left behind by a seat given up earlier: the base, so a fresh guard goes on.
  assert.deepEqual(locate(mark(CODE, 0, "seat-0"), ROOM, WHO), { kind: "base" });
  assert.deepEqual(locate({ [ROOM_ENTRY_KEY]: { code: CODE, depth: 0 } }, ROOM, WHO), { kind: "base" });
  // Another room's mark on this URL cannot happen, but is not ours if it does.
  assert.deepEqual(locate(mark("ZZ99ZZ", 0), ROOM, WHO), { kind: "base" });
  assert.deepEqual(locate(mark(CODE, -1), ROOM, WHO), { kind: "base" });
  assert.deepEqual(locate(mark(CODE, 0), "/settings/account", WHO), { kind: "elsewhere" });
});

test("a pushed entry keeps the router's location and moves its index on", () => {
  const state = pushedState({ usr: { overlayBackground: "/x" }, key: "k7", idx: 4 }, WHO, 1);
  assert.deepEqual(state, {
    usr: { overlayBackground: "/x" },
    key: "k7",
    idx: 5,
    [ROOM_ENTRY_KEY]: { code: CODE, seat: WHO.seat, depth: 1 },
  });
  assert.deepEqual(pushedState(null, WHO, 0), {
    [ROOM_ENTRY_KEY]: { code: CODE, seat: WHO.seat, depth: 0 },
  });
});

test("reconciling holds exactly one entry per open sheet above the guard", () => {
  const entry = (depth) => ({ kind: "entry", depth });
  assert.deepEqual(planReconcile({ kind: "base" }, 0), { push: [0] });
  assert.deepEqual(planReconcile({ kind: "base" }, 2), { push: [0, 1, 2] });
  assert.deepEqual(planReconcile(entry(0), 2), { push: [1, 2] });
  assert.deepEqual(planReconcile(entry(3), 1), { go: -2 });
  assert.equal(planReconcile(entry(1), 1), null);
  assert.equal(planReconcile({ kind: "elsewhere" }, 1), null);
});

test("a popstate is read by where it landed and whose it was", () => {
  const entry = (depth) => ({ kind: "entry", depth });
  assert.deepEqual(planPop(entry(0), 2, false), { kind: "close", count: 2 });
  assert.deepEqual(planPop(entry(2), 0, false), { kind: "go", delta: -2 });
  assert.deepEqual(planPop(entry(1), 1, false), { kind: "none" });
  assert.deepEqual(planPop(entry(0), 2, true), { kind: "reconcile" });
  assert.deepEqual(planPop({ kind: "base" }, 0, false), { kind: "back-on-room" });
  assert.deepEqual(planPop({ kind: "base" }, 0, true), { kind: "back-on-room" });
  assert.deepEqual(planPop({ kind: "elsewhere" }, 1, false), { kind: "none" });
});

test("leaving rewinds to the base from the room's entries, and nowhere else", () => {
  assert.deepEqual(exitStep({ kind: "entry", depth: 0 }), { kind: "rewind", delta: -1 });
  assert.deepEqual(exitStep({ kind: "entry", depth: 2 }), { kind: "rewind", delta: -3 });
  assert.deepEqual(exitStep({ kind: "base" }), { kind: "replace" });
  assert.deepEqual(exitStep({ kind: "elsewhere" }), { kind: "push" });
});

// --- The room's history, against a simulated browser ------------------------

test("entering a room puts the guard over the entry it was entered on", async () => {
  const { win } = await enterRoom();
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0]`);
});

test("a rejoin on a stale guard gets a guard of its own, so Back still leaves", async () => {
  // Leave, then Forward onto the entry the old seat's guard is still on, and
  // join again from the invite screen there: a new seat on an old mark, with
  // the lobby now the entry below it.
  const { win, room, port } = await enterRoom();
  leaveRoomHistory(port, WHO, (replace) => win.navigate("/", null, { replace }));
  await win.settle();
  room.stop();
  win.press(1);
  await win.settle();
  assert.equal(win.describe(), `/ / [${ROOM}#0]`);

  const rejoined = createRoomHistory(port, { code: CODE, seat: "seat-2" });
  const backs = [];
  rejoined.onBackOnRoom(() => backs.push(win.describe()));
  rejoined.start();
  await win.settle();
  assert.equal(win.describe(), `/ / ${ROOM}#0 [${ROOM}#0]`);

  // Back lands on the old seat's entry - the room's URL, this seat's base -
  // and is heard as Back on the room, not a walk out to the lobby.
  win.press(-1);
  await win.settle();
  assert.equal(backs.length, 1);
  assert.match(win.location.pathname, /^\/room\//);
});

test("StrictMode's stop and start again leaves one guard", async () => {
  const { win, room } = await enterRoom();
  room.stop();
  room.start();
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0]`);
});

test("a reload on the guard keeps it; one on a sheet's entry steps back to it", async () => {
  const win = new FakeWindow();
  win.navigate(ROOM);
  win.history.pushState(pushedState(win.history.state, WHO, 0));
  win.history.pushState(pushedState(win.history.state, WHO, 1));
  // The reload: a fresh room over the same stack, no sheet open.
  const room = createRoomHistory(historyPortFor(win), WHO);
  room.start();
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0] ${ROOM}#1`);
});

test("a sheet closed by its own control takes its entry back", async () => {
  const { win, room, backs } = await enterRoom();
  const sheet = openSheet(room, "menu");
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} ${ROOM}#0 [${ROOM}#1]`);

  sheet.close();
  await win.settle();
  assert.equal(win.index, 2, win.describe());
  assert.deepEqual(backs, []);

  // So one Back is Back on the room, not a press spent on a closed sheet.
  win.press(-1);
  await win.settle();
  assert.equal(backs.length, 1);
});

test("Back closes the topmost sheet, then the next, then asks to leave", async () => {
  const { win, room, backs } = await enterRoom();
  const players = openSheet(room, "players");
  await win.settle();
  const report = openSheet(room, "report");
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} ${ROOM}#0 ${ROOM}#1 [${ROOM}#2]`);

  win.press(-1);
  await win.settle();
  assert.equal(report.dismissedByBack, true);
  assert.equal(players.open, true);

  win.press(-1);
  await win.settle();
  assert.equal(players.dismissedByBack, true);
  assert.deepEqual(backs, []);

  win.press(-1);
  await win.settle();
  // Heard with the guard already back on top of the base.
  assert.deepEqual(backs, [`/ ${ROOM} [${ROOM}#0]`]);
});

test("sheets closing one after another wait for each other's traversal", async () => {
  const { win, room, port, backs } = await enterRoom();
  const lower = openSheet(room, "players");
  await win.settle();
  const upper = openSheet(room, "report");
  await win.settle();

  upper.close();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(port.inFlight(), 1);
  // Counted from the entry it is still on, this would ask for -2 on top of
  // the -1 in flight and land on the base: Back on the room nobody pressed.
  lower.close();
  await win.settle();
  assert.equal(win.index, 2, win.describe());
  assert.deepEqual(backs, []);
});

test("a sheet handing over to another in one render costs the history nothing", async () => {
  const { win, room } = await enterRoom();
  const highlights = openSheet(room, "highlights");
  await win.settle();
  highlights.close();
  openSheet(room, "recap");
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} ${ROOM}#0 [${ROOM}#1]`);
});

test("Back during a game opens the confirmation, and Back again cancels it", async () => {
  const { win, room, port } = await enterRoom();
  let confirmation = null;
  room.onBackOnRoom(() => {
    confirmation = openSheet(room, "leave-confirmation");
  });

  win.press(-1);
  await win.settle();
  assert.ok(confirmation?.open);
  assert.equal(win.describe(), `/ ${ROOM} ${ROOM}#0 [${ROOM}#1]`);

  win.press(-1);
  await win.settle();
  assert.equal(confirmation.dismissedByBack, true);
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0] ${ROOM}#1`);
  assert.equal(port.inFlight(), 0);
});

test("confirming a Leave asked for by Back rewinds to the base and replaces it", async () => {
  const { win, room, port } = await enterRoom();
  let confirmation = null;
  room.onBackOnRoom(() => {
    confirmation = openSheet(room, "leave-confirmation");
  });
  win.press(-1);
  await win.settle();

  const finished = [];
  // performLeave: the dialog closes as the room goes, and the lobby replaces.
  confirmation.close();
  leaveRoomHistory(port, WHO, (replace) => {
    finished.push(replace);
    win.navigate("/", null, { replace });
  });
  await win.settle();
  room.stop();
  assert.deepEqual(finished, [true]);
  assert.equal(win.describe(), `/ [/] ${ROOM}#0 ${ROOM}#1`);
});

test("Back in the waiting room leaves at once, from the guard", async () => {
  const { win, room, port } = await enterRoom();
  room.onBackOnRoom(() => {
    leaveRoomHistory(port, WHO, (replace) => win.navigate("/", null, { replace }));
  });
  win.press(-1);
  await win.settle();
  room.stop();
  assert.equal(win.describe(), `/ [/] ${ROOM}#0`);
});

test("leaving with sheets open takes every room entry off, not only the top", async () => {
  const { win, room, port } = await enterRoom();
  const players = openSheet(room, "players");
  await win.settle();
  openSheet(room, "report");
  await win.settle();

  // A kick, say: the room unmounts under its sheets as the rewind starts.
  leaveRoomHistory(port, WHO, (replace) => win.navigate("/", { criticalError: "x" }, { replace }));
  players.close();
  await win.settle();
  room.stop();
  assert.equal(win.describe(), `/ [/] ${ROOM}#0 ${ROOM}#1 ${ROOM}#2`);
  assert.deepEqual(win.history.state.usr, { criticalError: "x" });
});

test("a leave waits for a traversal already in flight before counting its rewind", async () => {
  const { win, room, port } = await enterRoom();
  const sheet = openSheet(room, "menu");
  await win.settle();
  sheet.close();
  // Let the release's reconcile ask for its traversal, but not land it.
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(port.inFlight(), 1);

  leaveRoomHistory(port, WHO, (replace) => win.navigate("/", null, { replace }));
  await win.settle();
  room.stop();
  // Counted from the guard it landed on (-1), not the sheet it left (-2),
  // which would have gone past the base into the lobby.
  assert.equal(win.describe(), `/ [/] ${ROOM}#0 ${ROOM}#1`);
});

test("a second way out during a leave is left to the first", async () => {
  const { win, room, port } = await enterRoom();
  const calls = [];
  leaveRoomHistory(port, WHO, (replace) => {
    calls.push("leave");
    win.navigate("/", null, { replace });
  });
  leaveRoomHistory(port, WHO, () => calls.push("kicked"));
  await win.settle();
  room.stop();
  assert.deepEqual(calls, ["leave"]);
  assert.equal(win.describe(), `/ [/] ${ROOM}#0`);
});

test("only a sheet's entry is one an overlay replaces", () => {
  const mark = (depth, seat = "anyone") => ({ [ROOM_ENTRY_KEY]: { code: CODE, seat, depth } });
  assert.equal(isSheetEntry(mark(1)), true);
  assert.equal(isSheetEntry(mark(2, WHO.seat)), true);
  // The guard stays under an overlay: replacing it would lose Back on the room.
  assert.equal(isSheetEntry(mark(0)), false);
  assert.equal(isSheetEntry({ usr: null, key: "a", idx: 1 }), false);
  assert.equal(isSheetEntry(null), false);
});

test("an overlay opened from a menu takes its entry, so Back and Forward both work", async () => {
  const { win, room, backs } = await enterRoom();
  const menu = openSheet(room, "account-menu");
  await win.settle();
  // The menu's Settings row: useOpenOverlay replaces a sheet's entry.
  menu.close();
  win.navigate("/settings/account", { overlayBackground: ROOM }, {
    replace: isSheetEntry(win.history.state),
  });
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} ${ROOM}#0 [/settings/account]`);

  win.press(-1);
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0] /settings/account`);
  win.press(1);
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} ${ROOM}#0 [/settings/account]`);
  assert.deepEqual(backs, []);
});

test("an overlay pushed over a sheet's stale entry: Back from it steps over the entry", async () => {
  const { win, room, backs } = await enterRoom();
  const menu = openSheet(room, "menu");
  await win.settle();
  // The menu's Settings row: the sheet closes and the router pushes Settings.
  menu.close();
  win.navigate("/settings/account", { overlayBackground: ROOM });
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} ${ROOM}#0 ${ROOM}#1 [/settings/account]`);

  win.press(-1);
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0] ${ROOM}#1 /settings/account`);
  assert.deepEqual(backs, []);
});

test("an overlay opened from the room closes on Back and leaves the room alone", async () => {
  const { win, backs } = await enterRoom();
  win.navigate("/settings/sound", { overlayBackground: ROOM });
  win.press(-1);
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0] /settings/sound`);
  assert.deepEqual(backs, []);
});

test("an overlay over an open sheet leaves the sheet's entry under it", async () => {
  const { win, room } = await enterRoom();
  const sheet = openSheet(room, "room-settings");
  await win.settle();
  win.navigate("/settings/account", { overlayBackground: ROOM });
  win.press(-1);
  await win.settle();
  assert.equal(sheet.open, true);
  assert.equal(win.describe(), `/ ${ROOM} ${ROOM}#0 [${ROOM}#1] /settings/account`);
});

test("Forward onto a closed sheet's entry does not reopen anything", async () => {
  const { win, room, backs } = await enterRoom();
  openSheet(room, "menu");
  await win.settle();
  win.press(-1);
  await win.settle();
  win.press(1);
  await win.settle();
  assert.equal(win.index, 2, win.describe());
  assert.deepEqual(backs, []);
});

test("a long jump back past every room entry is still Back on the room", async () => {
  const { win, room, backs } = await enterRoom();
  const one = openSheet(room, "one");
  await win.settle();
  const two = openSheet(room, "two");
  await win.settle();
  win.press(-3);
  await win.settle();
  assert.equal(one.dismissedByBack && two.dismissedByBack, true);
  assert.equal(backs.length, 1);
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0]`);
});

test("a traversal the browser drops is given up rather than waited on for good", async () => {
  const win = new FakeWindow();
  win.navigate(ROOM);
  // A mark that lies about how deep it is: the rewind goes past the start.
  win.history.pushState(pushedState(win.history.state, WHO, 5));
  const port = historyPortFor(win);
  const finished = [];
  leaveRoomHistory(port, WHO, (replace) => finished.push(replace));
  await win.settle();
  assert.deepEqual(finished, []);
  await win.fireTimers();
  assert.deepEqual(finished, [true]);
  assert.equal(port.inFlight(), 0);
});

test("once a leave lands, the next room's history works on the same window", async () => {
  const { win, room, port } = await enterRoom();
  leaveRoomHistory(port, WHO, (replace) => win.navigate("/", null, { replace }));
  await win.settle();
  room.stop();

  win.navigate("/room/ZZ99ZZ");
  const next = createRoomHistory(port, { code: "ZZ99ZZ", seat: "seat-9" });
  next.start();
  await win.settle();
  assert.match(win.describe(), /\[\/room\/ZZ99ZZ#0\]$/);
});

test("a seat given up in place (signing in) rewinds without navigating", async () => {
  // Signing in or out in a room clears the seat and stays on the room's URL,
  // now the invite screen. Rewound to the base, a rejoin there gets a guard
  // of its own, and leaving that seat leaves no room entry under the lobby.
  const { win, room, port } = await enterRoom();
  openSheet(room, "sign-in");
  await win.settle();
  leaveRoomHistory(port, WHO, () => {});
  await win.settle();
  room.stop();
  assert.equal(win.describe(), `/ [${ROOM}] ${ROOM}#0 ${ROOM}#1`);

  const signedIn = { code: CODE, seat: "seat-2" };
  const rejoined = createRoomHistory(port, signedIn);
  rejoined.start();
  await win.settle();
  assert.equal(win.describe(), `/ ${ROOM} [${ROOM}#0]`);

  leaveRoomHistory(port, signedIn, (replace) => win.navigate("/", null, { replace }));
  await win.settle();
  rejoined.stop();
  assert.equal(win.describe(), `/ [/] ${ROOM}#0`);
});

test("outside the room's entries a leave is an ordinary push", async () => {
  const { win, port } = await enterRoom();
  win.navigate("/settings/account", { overlayBackground: ROOM });
  const finished = [];
  leaveRoomHistory(port, WHO, (replace) => finished.push(replace));
  assert.deepEqual(finished, [false]);
});
