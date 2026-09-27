import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ToastContext,
  keepRecentToasts,
  sameToast,
  type ToastAction,
  type ToastTone,
} from "../lib/toast";
import { XIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
  action?: ToastAction;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextIdRef = useRef(1);
  const timersRef = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  // A toast is on screen exactly while its timer is registered: the timer is
  // dropped when it fires, when the toast is closed and when it is pushed off
  // the stack. So that map answers whether there was anything to take down.
  const dismiss = useCallback((id: number) => {
    const timer = timersRef.current.get(id);
    if (timer) clearTimeout(timer);
    const shown = timersRef.current.delete(id);
    setToasts((current) => current.filter((toast) => toast.id !== id));
    return shown;
  }, []);

  const notify = useCallback((
    message: string,
    tone: ToastTone,
    durationMs = 5000,
    action?: ToastAction,
  ) => {
    const id = nextIdRef.current++;
    setToasts((current) => {
      const { kept, evicted } = keepRecentToasts(
        current,
        { id, message, tone, action },
        sameToast,
      );
      // A toast that fell off the stack still has a timer running against it.
      for (const gone of evicted) {
        const timer = timersRef.current.get(gone.id);
        if (timer) clearTimeout(timer);
        timersRef.current.delete(gone.id);
      }
      return kept;
    });
    timersRef.current.set(id, setTimeout(() => dismiss(id), durationMs));
    return id;
  }, [dismiss]);

  useEffect(() => () => {
    for (const timer of timersRef.current.values()) clearTimeout(timer);
    timersRef.current.clear();
  }, []);

  // One object for the provider's lifetime: a fresh `{ notify }` on every
  // render re-rendered all of its consumers - the live room among them - each
  // time a toast came or went (#987).
  const contextValue = useMemo(() => ({ notify, dismiss }), [notify, dismiss]);

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      <div className="toast-viewport" role="region" aria-label={ui.toastProvider.notifications}>
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`app-toast ${toast.tone}`}
            role={toast.tone === "error" ? "alert" : "status"}
          >
            <span>{toast.message}</span>
            {/* Dismissed as it fires: the thing it offered has been done, and
                a toast still sitting there with a button that would now do
                nothing is worse than no button. */}
            {toast.action && (
              <button
                type="button"
                className="app-toast-action"
                onClick={() => {
                  dismiss(toast.id);
                  toast.action?.onClick();
                }}
              >
                {toast.action.label}
              </button>
            )}
            <button type="button" onClick={() => dismiss(toast.id)} aria-label={ui.toastProvider.dismissNotification}><XIcon size={14} /></button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
