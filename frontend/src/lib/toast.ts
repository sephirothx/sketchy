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

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
