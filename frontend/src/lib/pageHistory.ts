/** What the browser's Back does to a layer opened over a page that is not a
room (R-UX-15): the drawing viewer opened from the profile's game history or
its pinned shelf.

A room keeps entries of its own on the history stack (`roomHistory.ts`), so
Back closes whatever is open over it. Outside a room nothing did: Back from
the drawing viewer on a profile left the page with the viewer still drawn
over it - the most natural way out on a phone, where Back is a gesture made
without thinking, and one more site among the many that break that
expectation of a viewer laid over a page.

So a page does the same as a room, without the room's guard and seat: one
entry per open **layer**, on the page's own URL, told apart by a mark in
`history.state` naming the page and the layer's depth (1, 2, …). Back lands
one lower and the topmost layer closes; a layer closed by its own control
takes its entry back, so Back never has to be pressed once per layer opened
earlier. Entries are counted, never named, as the room's sheets are.

A layer left open as the page is navigated away from leaves its entries in the
back history. Landing on one with nothing open steps over it the way the
player was going - Back on to the page under it, Forward on to the page after
it - so it costs them nothing. One case is left: a reload with a layer open
lands on its entry with nothing listening yet, and the first Back is spent
staying on the page.

The module imports only the room's history port, which keeps `history.go`
asynchronous and counts the traversals asked for; the tests drive a simulated
history through it. */

import type { HistoryPort } from "./roomHistory";

/** The key in `history.state` that marks one of a page's layer entries. Beside
the router's own keys, never inside `usr`, so the router's `location.state`
does not change when a layer opens. */
export const PAGE_LAYER_KEY = "sketchyPageLayer";

interface PageLayerMark {
  path: string;
  depth: number;
}

function markOf(state: unknown): PageLayerMark | null {
  if (!state || typeof state !== "object") return null;
  const mark = (state as Record<string, unknown>)[PAGE_LAYER_KEY];
  if (!mark || typeof mark !== "object") return null;
  const { path, depth } = mark as Partial<PageLayerMark>;
  if (typeof path !== "string" || typeof depth !== "number") return null;
  if (!Number.isInteger(depth) || depth < 1) return null;
  return { path, depth };
}

/** How many layer entries deep the current entry is: 0 on the page itself, or
on any entry another page's layer marked. */
export function layerDepth(state: unknown, pathname: string): number {
  const mark = markOf(state);
  return mark && mark.path === pathname ? mark.depth : 0;
}

/** The state for a layer entry pushed on top of `state`: the router's keys
kept, so it still reads the same location, its index moved on by one as a
push of its own would, and the mark added. */
export function layerState(state: unknown, path: string, depth: number): Record<string, unknown> {
  const base = state && typeof state === "object" ? (state as Record<string, unknown>) : {};
  const mark: PageLayerMark = { path, depth };
  const next: Record<string, unknown> = { ...base, [PAGE_LAYER_KEY]: mark };
  if (typeof base.idx === "number") next.idx = base.idx + 1;
  return next;
}

/** What to do to the history so it holds exactly `open` layer entries. */
export type LayerStep = { push: number[] } | { go: number } | null;

export function planLayers(depth: number, open: number): LayerStep {
  if (depth < open) {
    const push: number[] = [];
    for (let next = depth + 1; next <= open; next += 1) push.push(next);
    return { push };
  }
  if (depth > open) return { go: open - depth };
  return null;
}

/** What a `popstate` means for the layers open now. */
export type LayerPop =
  | { kind: "none" }
  /** Back past this many layers: close them, topmost first. */
  | { kind: "close"; count: number }
  /** Landed on layer entries nothing is open for any more: step over them. */
  | { kind: "go"; delta: number }
  /** Our own traversal landed: bring the history in line with what is open. */
  | { kind: "reconcile" };

export function planLayerPop(
  depth: number,
  open: number,
  ownTraversal: boolean,
  forward = false,
): LayerPop {
  if (ownTraversal) return { kind: "reconcile" };
  if (depth < open) return { kind: "close", count: open - depth };
  // A leftover entry with nothing open: on past it, whichever way the player
  // was going, or Forward would bounce off it for good.
  if (depth > open) return { kind: "go", delta: forward && open === 0 ? 1 : open - depth };
  return { kind: "none" };
}

/** The router's index of an entry, which says which way a traversal went. */
function indexOf(state: unknown): number | null {
  if (!state || typeof state !== "object") return null;
  const idx = (state as Record<string, unknown>).idx;
  return typeof idx === "number" ? idx : null;
}

export interface PageHistory {
  /** A layer opened. Back closes it through `dismiss`. The returned release is
  for when it closes any other way, and does nothing once Back has closed it. */
  open(dismiss: () => void): () => void;
}

export function createPageHistory(port: HistoryPort): PageHistory {
  const layers: { dismiss: () => void }[] = [];
  // The page the open layers belong to; their entries are marked with it.
  let path = port.pathname();
  // The entry last seen, to tell Forward from Back when one lands.
  let lastIndex = indexOf(port.state());
  let unlisten: (() => void) | null = null;
  let scheduled = false;

  const depth = () => layerDepth(port.state(), path);

  function reconcile() {
    scheduled = false;
    // Mid-traversal the current entry is about to change under us: wait for
    // it to land, which schedules this again.
    if (port.inFlight() > 0) return;
    // Navigated away under the layers: their entries are behind, not here.
    if (port.pathname() !== path) return;
    const step = planLayers(depth(), layers.length);
    if (!step) return;
    if ("go" in step) {
      port.go(step.go);
      return;
    }
    let state = port.state();
    for (const next of step.push) {
      state = layerState(state, path, next);
      port.pushState(state);
    }
    lastIndex = indexOf(state);
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    port.defer(reconcile);
  }

  function onSettle(own: boolean) {
    const index = indexOf(port.state());
    const forward = index !== null && lastIndex !== null && index > lastIndex;
    lastIndex = index;
    // With nothing open the layers belong to no page: whatever page this is,
    // a leftover entry of its own is stepped over.
    if (layers.length === 0) path = port.pathname();
    if (port.pathname() !== path) return;
    const plan = planLayerPop(depth(), layers.length, own, forward);
    switch (plan.kind) {
      case "close": {
        // Out of the list before they are told, so the reconcile their closing
        // schedules finds the history already where it should be.
        const closing = layers.splice(layers.length - plan.count, plan.count).reverse();
        for (const layer of closing) layer.dismiss();
        break;
      }
      case "go":
        port.go(plan.delta);
        break;
      case "reconcile":
        schedule();
        break;
      case "none":
        break;
    }
  }

  return {
    open(dismiss) {
      if (layers.length === 0) path = port.pathname();
      unlisten ??= port.listen(onSettle);
      const layer = { dismiss };
      layers.push(layer);
      schedule();
      return () => {
        const index = layers.indexOf(layer);
        if (index < 0) return;
        layers.splice(index, 1);
        schedule();
      };
    },
  };
}
