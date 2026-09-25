/** What the browser's Back does in a room (R-UX-15).

Back used to be the router's: it unmounted the room and drew the page before
it, without `leave_room`, so the seat stayed live in a room nobody was looking
at - the same hole the crash page's way out closes (R-UX-06). And a sheet
opened over the room was local state that Back walked straight past. On a
phone, where Back is a gesture people make without thinking, that was the
easiest way out of a game by accident.

So a room keeps entries of its own on the history stack, all on the room's URL
and told apart by a mark in `history.state`:

* the **guard**, depth 0, pushed over the entry the room was opened on (the
  **base**). Back from the guard lands on the base, which is how Back on the
  room is heard at all: it is the room's own Leave, re-armed first, so it asks
  during a game and leaves at once otherwise, exactly as the Leave row does;
* one entry per open **sheet** above it, depth 1, 2, …. Back lands one lower
  and the topmost sheet closes. A sheet closed by its own control takes its
  entry back with it, so the stack stays balanced and Back never has to be
  pressed once per sheet somebody opened earlier.

The entries are counted, never named: which sheet is on top is this module's
list, and the history only has to hold as many entries as there are sheets.
That is what makes a close and an open in one render (Highlights handing over
to the drawing it names) cost the history nothing.

Leaving rewinds to the base and replaces it with the lobby, so Back from the
lobby goes to wherever the room was entered from rather than to a room that is
gone, and no guard or sheet entry is left behind it.

The browser is behind `HistoryPort`, and the module imports nothing, so the
tests drive a simulated history with no bundler and no DOM. `history.go` is
asynchronous in a browser and the port keeps it that way, which is the part of
this worth testing. */

/** The key in `history.state` that marks one of a room's own entries. Beside
the router's own keys, never inside `usr`, so the router's `location.state`
does not change when a sheet opens. */
export const ROOM_ENTRY_KEY = "sketchyRoomEntry";

interface RoomEntryMark {
  code: string;
  depth: number;
}

/** Where the current history entry is, from the room's point of view. */
export type Landing =
  /** One of the room's own entries: 0 the guard, n the nth sheet. */
  | { kind: "entry"; depth: number }
  /** The room's URL without a mark: the entry the room was opened on. */
  | { kind: "base" }
  /** Anything else - another page, or an overlay drawn over the room. */
  | { kind: "elsewhere" };

export function isRoomPath(pathname: string, code: string): boolean {
  // The router matches case-insensitively and tolerates a trailing slash.
  return pathname.replace(/\/+$/, "").toUpperCase() === `/ROOM/${code.toUpperCase()}`;
}

function markOf(state: unknown): RoomEntryMark | null {
  if (!state || typeof state !== "object") return null;
  const mark = (state as Record<string, unknown>)[ROOM_ENTRY_KEY];
  if (!mark || typeof mark !== "object") return null;
  const { code, depth } = mark as Partial<RoomEntryMark>;
  if (typeof code !== "string" || typeof depth !== "number") return null;
  if (!Number.isInteger(depth) || depth < 0) return null;
  return { code, depth };
}

export function locate(state: unknown, pathname: string, code: string): Landing {
  if (!isRoomPath(pathname, code)) return { kind: "elsewhere" };
  const mark = markOf(state);
  if (mark && mark.code.toUpperCase() === code.toUpperCase()) {
    return { kind: "entry", depth: mark.depth };
  }
  return { kind: "base" };
}

/** The state for an entry pushed on top of `state`: the router's keys kept, so
it still reads the same location, its index moved on by one as a push of its
own would, and the mark added. */
export function pushedState(state: unknown, code: string, depth: number): Record<string, unknown> {
  const base = state && typeof state === "object" ? (state as Record<string, unknown>) : {};
  const next: Record<string, unknown> = { ...base, [ROOM_ENTRY_KEY]: { code, depth } };
  if (typeof base.idx === "number") next.idx = base.idx + 1;
  return next;
}

/** What to do to the history so it holds exactly `open` sheet entries above
the guard. */
export type HistoryStep = { push: number[] } | { go: number } | null;

export function planReconcile(landing: Landing, open: number): HistoryStep {
  if (landing.kind === "elsewhere") return null;
  const from = landing.kind === "base" ? -1 : landing.depth;
  if (from < open) {
    const push: number[] = [];
    for (let depth = from + 1; depth <= open; depth += 1) push.push(depth);
    return { push };
  }
  if (from > open) return { go: open - from };
  return null;
}

/** What a `popstate` means. */
export type PopPlan =
  | { kind: "none" }
  /** Back past this many sheets: close them, topmost first. */
  | { kind: "close"; count: number }
  /** Landed on sheet entries nothing is open for any more - Forward into one,
  or Back from an overlay opened as a sheet closed. Step over them. */
  | { kind: "go"; delta: number }
  /** Our own traversal landed: bring the history in line with what is open now. */
  | { kind: "reconcile" }
  /** Back from the guard: the room's own Leave. */
  | { kind: "back-on-room" };

export function planPop(landing: Landing, open: number, ownTraversal: boolean): PopPlan {
  if (landing.kind === "elsewhere") return { kind: "none" };
  // Our traversals never go below the guard, so the base is always somebody's Back.
  if (landing.kind === "base") return { kind: "back-on-room" };
  if (ownTraversal) return { kind: "reconcile" };
  if (landing.depth < open) return { kind: "close", count: open - landing.depth };
  if (landing.depth > open) return { kind: "go", delta: open - landing.depth };
  return { kind: "none" };
}

/** How to get off the room's entries on the way out. */
export type ExitStep =
  /** Rewind to the base, then replace it. */
  | { kind: "rewind"; delta: number }
  /** Already on the base: replace it. */
  | { kind: "replace" }
  /** On an entry that is not the room's (an overlay over it): push, as any
  other navigation from there would. */
  | { kind: "push" };

export function exitStep(landing: Landing): ExitStep {
  if (landing.kind === "entry") return { kind: "rewind", delta: -(landing.depth + 1) };
  if (landing.kind === "base") return { kind: "replace" };
  return { kind: "push" };
}


/** The parts of `window` the port uses - `window` itself in the app, a
simulated history in the tests. */
export interface HistoryWindow {
  readonly history: {
    readonly state: unknown;
    pushState(data: unknown, unused: string): void;
    go(delta: number): void;
  };
  readonly location: { readonly pathname: string };
  addEventListener(type: "popstate", listener: () => void): void;
  setTimeout(handler: () => void, ms: number): number;
  clearTimeout(id: number): void;
  queueMicrotask(task: () => void): void;
}

/** The browser's history, as much of it as a room touches.

`go` is asynchronous and answered by a `popstate`, so the port counts the
traversals it has asked for: a `popstate` while any is in flight answers one
of them, and is reported to listeners as the room's own rather than as
somebody pressing Back. A traversal the browser never answers (a `go` past
either end of the stack does nothing) is given up after
`TRAVERSAL_TIMEOUT_MS`, and listeners hear that as one last own settle, so
nothing waits on it for good. */
export interface HistoryPort {
  state(): unknown;
  pathname(): string;
  /** `history.pushState` on the current URL. Synchronous, and fires nothing. */
  pushState(state: unknown): void;
  go(delta: number): void;
  /** Traversals asked for and not yet answered. */
  inFlight(): number;
  /** Every `popstate`, and every traversal given up; `own` when it settled a
  traversal the port was asked for. Returns the unsubscribe. */
  listen(onSettle: (own: boolean) => void): () => void;
  /** After the current task's state updates have been committed. */
  defer(task: () => void): void;
}

/** Same-document traversals land within a frame; this is only there so one
the browser dropped cannot wedge a room's history. */
export const TRAVERSAL_TIMEOUT_MS = 1000;

const ports = new WeakMap<HistoryWindow, HistoryPort>();

/** The one port for a window: one `popstate` listener, one in-flight count. */
export function historyPortFor(win: HistoryWindow): HistoryPort {
  const existing = ports.get(win);
  if (existing) return existing;
  const listeners = new Set<(own: boolean) => void>();
  let inFlight = 0;
  let timer: number | null = null;
  const notify = (own: boolean) => {
    for (const listener of [...listeners]) listener(own);
  };
  const clearTimer = () => {
    if (timer !== null) win.clearTimeout(timer);
    timer = null;
  };
  win.addEventListener("popstate", () => {
    const own = inFlight > 0;
    if (own) {
      inFlight -= 1;
      if (inFlight === 0) clearTimer();
    }
    notify(own);
  });
  const port: HistoryPort = {
    state: () => win.history.state,
    pathname: () => win.location.pathname,
    pushState: (state) => win.history.pushState(state, ""),
    go(delta) {
      inFlight += 1;
      clearTimer();
      timer = win.setTimeout(() => {
        timer = null;
        if (inFlight === 0) return;
        inFlight = 0;
        notify(true);
      }, TRAVERSAL_TIMEOUT_MS);
      win.history.go(delta);
    },
    inFlight: () => inFlight,
    listen(onSettle) {
      listeners.add(onSettle);
      return () => {
        listeners.delete(onSettle);
      };
    },
    defer: (task) => win.queueMicrotask(task),
  };
  ports.set(win, port);
  return port;
}

/** Ports with a leave in progress. A room's controller stands aside on one, so
the traversal the leave makes is not read as Back, and the sheets the room
closes on its way out do not try to take their entries back as well. */
const leaving = new WeakSet<HistoryPort>();

export interface RoomHistory {
  /** Start listening, and put the guard on the stack if it is not there.
  Safe to call again after `stop`, as StrictMode does to every effect. */
  start(): void;
  stop(): void;
  /** A sheet opened. Back closes it through `dismiss`. The returned release is
  for when it closes any other way, and does nothing once Back has closed it. */
  open(dismiss: () => void): () => void;
  /** What Back on the room itself does: the room's own Leave. */
  onBackOnRoom(handler: () => void): void;
}

export function createRoomHistory(port: HistoryPort, code: string): RoomHistory {
  const sheets: { dismiss: () => void }[] = [];
  let backOnRoom: () => void = () => {};
  let unlisten: (() => void) | null = null;
  let scheduled = false;

  const active = () => unlisten !== null && !leaving.has(port);
  const landing = () => locate(port.state(), port.pathname(), code);

  function apply(step: HistoryStep) {
    if (!step) return;
    if ("go" in step) {
      port.go(step.go);
      return;
    }
    let state = port.state();
    for (const depth of step.push) {
      state = pushedState(state, code, depth);
      port.pushState(state);
    }
  }

  function reconcile() {
    scheduled = false;
    // Mid-traversal the current entry is about to change under us: wait for
    // it to land, which schedules this again.
    if (!active() || port.inFlight() > 0) return;
    apply(planReconcile(landing(), sheets.length));
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    port.defer(reconcile);
  }

  function closeTop(count: number) {
    // Out of the list before they are told, so the reconcile their closing
    // schedules finds the history already where it should be.
    const closing = sheets.splice(sheets.length - count, count).reverse();
    for (const sheet of closing) sheet.dismiss();
  }

  function onSettle(own: boolean) {
    if (!active()) return;
    const plan = planPop(landing(), sheets.length, own);
    switch (plan.kind) {
      case "close":
        closeTop(plan.count);
        break;
      case "go":
        port.go(plan.delta);
        break;
      case "reconcile":
        schedule();
        break;
      case "back-on-room":
        // Whatever was open goes and the guard comes back, before Leave runs:
        // a Leave that asks then has the guard under its dialog, and one that
        // does not rewinds from the guard like any other.
        closeTop(sheets.length);
        apply(planReconcile(landing(), 0));
        backOnRoom();
        break;
      case "none":
        break;
    }
  }

  return {
    start() {
      if (unlisten) return;
      unlisten = port.listen(onSettle);
      schedule();
    },
    stop() {
      unlisten?.();
      unlisten = null;
    },
    open(dismiss) {
      const sheet = { dismiss };
      sheets.push(sheet);
      schedule();
      return () => {
        const index = sheets.indexOf(sheet);
        if (index < 0) return;
        sheets.splice(index, 1);
        schedule();
      };
    },
    onBackOnRoom(handler) {
      backOnRoom = handler;
    },
  };
}

/** Take the room's entries off the stack on the way out, then `finish` -
`replace` true when it lands on the base the room was entered on, which the
lobby should take the place of.

Module-level rather than a method, because the ways out run as the room
unmounts: the seat is given up and the store reset before the traversal lands,
and the crash page's way out has no room mounted at all. A traversal the room
already had in flight is let land first, since the rewind is counted from
wherever it lands. */
export function leaveRoomHistory(
  port: HistoryPort,
  code: string,
  finish: (replace: boolean) => void,
): void {
  // A second way out while the first is rewinding (a kick arriving under a
  // Leave) would count its rewind from an entry about to be left. The first
  // is already taking the player to the lobby.
  if (leaving.has(port)) return;
  leaving.add(port);
  let rewinding = false;
  let finished = false;
  let unlisten: () => void = () => {};
  const done = (replace: boolean) => {
    finished = true;
    unlisten();
    leaving.delete(port);
    finish(replace);
  };
  const step = () => {
    if (finished || port.inFlight() > 0) return;
    // Landed on the base - or, if the browser dropped the traversal, still on
    // one of the room's entries. Replacing is right for both.
    if (rewinding) return done(true);
    const exit = exitStep(locate(port.state(), port.pathname(), code));
    if (exit.kind !== "rewind") return done(exit.kind === "replace");
    rewinding = true;
    port.go(exit.delta);
  };
  unlisten = port.listen(step);
  step();
}
