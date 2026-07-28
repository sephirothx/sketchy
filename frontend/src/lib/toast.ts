import { createContext, useContext } from "react";

export type ToastTone = "info" | "success" | "warning" | "error";

export interface ToastContextValue {
  notify: (message: string, tone?: ToastTone, durationMs?: number) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
