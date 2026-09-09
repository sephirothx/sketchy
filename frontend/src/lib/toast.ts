import { createContext, useContext } from "react";

export type ToastTone = "info" | "success" | "warning" | "error";

/** One thing a toast may offer to do about what it just said.

Deliberately one, and deliberately not a destructive one: a toast can be
pushed off the stack by the next one and dismisses itself on a timer, so it is
the wrong place for a decision somebody has to get right. Accepting a friend
request qualifies — it is the answer most people want, and the other answer
stays on the friends surface where it is confirmed (R-FRIEND-10). */
export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastContextValue {
  notify: (
    message: string,
    tone?: ToastTone,
    durationMs?: number,
    action?: ToastAction,
  ) => void;
}

/** How many toasts stand at once.

Three was too few. A notice that has to be *acted on* - a friend request
carrying Accept (R-FRIEND-12) - was being pushed off the stack by two
informational ones that happened to land first, and then the only way to
answer was to go looking for the friends surface. Losing an unread "your
export is ready" costs nothing; losing the one with a button on it costs the
thing it was for.

Five, not more: past that a stack of toasts is its own problem, and the answer
to "everything is shouting" is not a taller pile. */
export const MAX_TOASTS = 5;

/** The stack after one more toast arrives, and which ones fell off it.

Split out from the provider because it is the rule, not the rendering: what a
player keeps when several notices land at once is worth being able to test
without a browser. The evicted ones are returned so their timers can be
cleared - a dropped toast whose timer still runs leaves an entry behind and
fires a dismissal for something nobody can see. */
export function keepRecentToasts<T>(current: T[], arriving: T): {
  kept: T[];
  evicted: T[];
} {
  const room = Math.max(0, MAX_TOASTS - 1);
  return {
    kept: [...current.slice(-room), arriving],
    evicted: current.slice(0, Math.max(0, current.length - room)),
  };
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
