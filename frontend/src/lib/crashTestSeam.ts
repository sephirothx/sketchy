/** A way for the E2E suite to make a screen throw.

A crash boundary can only be tested by crashing something under it, and no
shipped component throws on request. This arms one: `<CrashProbe>` sits inside
each boundary and throws on its next render once `window.__SKETCHY_CRASH__` has
named its scope. The arming is undone a tick later, from outside any render:
React retries a throwing component once before handing the error to a boundary,
so a probe that disarmed itself in render would sometimes crash nothing - and
the render after Reload or Back to lobby has to be a clean one.

Gated on the same build flag as `renderDiagnostics.ts`: `scripts/test-e2e.sh`
builds with `VITE_RENDER_DIAGNOSTICS=true`, a production build does not, and in
that build the probe renders nothing and the window hook is never installed. */

import { useSyncExternalStore } from "react";
import type { CrashScope } from "./crashReport";

type SeamWindow = Window & {
  __SKETCHY_CRASH__?: (scope: CrashScope) => void;
};

const enabled = import.meta.env.VITE_RENDER_DIAGNOSTICS === "true";

let armed: CrashScope | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): CrashScope | null {
  return armed;
}

function notify(): void {
  listeners.forEach((listener) => listener());
}

function armCrash(scope: CrashScope): void {
  armed = scope;
  notify();
  // A macrotask: React flushes the store update, renders, retries, and hands
  // the error to the boundary before this runs.
  window.setTimeout(() => {
    armed = null;
    notify();
  }, 0);
}

/** Expose the hook, in a diagnostics build only. */
export function installCrashTestSeam(): void {
  if (!enabled) return;
  (window as SeamWindow).__SKETCHY_CRASH__ = armCrash;
}

/** Renders nothing - until it is asked to throw. */
export function CrashProbe({ scope }: { scope: CrashScope }) {
  const current = useSyncExternalStore(subscribe, snapshot, snapshot);
  if (enabled && current === scope) {
    throw new Error(`Test crash: ${scope}`);
  }
  return null;
}
