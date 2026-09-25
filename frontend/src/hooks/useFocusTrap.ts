import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "a[href]",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => element.offsetParent !== null || element.getClientRects().length > 0,
  );
}

/** Where focus starts: the element asked for, else the first control in the
 * body. A dialog's ✕ comes first in the markup but is marked to be passed
 * over, because starting there puts Enter one press from abandoning whatever
 * the dialog was opened to do. The element asked for can also refuse focus -
 * a button still disabled while the dialog loads - and the same fallback
 * keeps focus from staying on the page behind. */
function initialFocus(container: HTMLElement, requested: HTMLElement | null) {
  requested?.focus();
  if (container.contains(document.activeElement)) return;
  const focusable = getFocusableElements(container);
  const first = focusable.find((element) => !element.hasAttribute("data-skip-initial-focus"));
  (first ?? focusable[0] ?? container).focus();
}

type DismissLayer = {
  dismiss: () => void;
};

type TabLayer = {
  container: HTMLElement;
};

const escapeStack: DismissLayer[] = [];
const tabStack: TabLayer[] = [];
let documentListenerBound = false;

function handleDocumentKeyDown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    const top = escapeStack[escapeStack.length - 1];
    if (!top) return;
    event.preventDefault();
    event.stopPropagation();
    top.dismiss();
    return;
  }

  if (event.key !== "Tab") return;
  const top = tabStack[tabStack.length - 1];
  if (!top) return;
  const focusable = getFocusableElements(top.container);
  if (!focusable.length) {
    event.preventDefault();
    top.container.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function bindDocumentListener() {
  if (documentListenerBound) return;
  document.addEventListener("keydown", handleDocumentKeyDown, true);
  documentListenerBound = true;
}

function unbindDocumentListenerIfIdle() {
  if (escapeStack.length > 0 || tabStack.length > 0) return;
  document.removeEventListener("keydown", handleDocumentKeyDown, true);
  documentListenerBound = false;
}

/** Register a dismissible surface. Escape closes the topmost layer only. */
export function useEscapeLayer(active: boolean, onEscape: () => void) {
  const onEscapeRef = useRef(onEscape);
  useEffect(() => {
    onEscapeRef.current = onEscape;
  });

  useEffect(() => {
    if (!active) return;
    const layer: DismissLayer = { dismiss: () => onEscapeRef.current() };
    escapeStack.push(layer);
    bindDocumentListener();
    return () => {
      const index = escapeStack.lastIndexOf(layer);
      if (index >= 0) escapeStack.splice(index, 1);
      unbindDocumentListenerIfIdle();
    };
  }, [active]);
}

interface UseFocusTrapOptions {
  active?: boolean;
  onEscape?: () => void;
  initialFocusRef?: RefObject<HTMLElement | null>;
}

/**
 * Trap Tab within `containerRef`, move initial focus in, and restore focus on
 * unmount. Optional Escape dismissal uses the shared layer stack so nested
 * surfaces close from the top down.
 */
export function useFocusTrap(
  containerRef: RefObject<HTMLElement | null>,
  options: UseFocusTrapOptions = {},
) {
  const { active = true, onEscape, initialFocusRef } = options;
  const previousFocusRef = useRef<HTMLElement | null>(null);
  // What had focus before this component rendered at all, read once.
  const [focusAtMount] = useState<Element | null>(() =>
    typeof document === "undefined" ? null : document.activeElement,
  );
  const onEscapeRef = useRef(onEscape);
  useEffect(() => {
    onEscapeRef.current = onEscape;
  });

  useEscapeLayer(Boolean(active && onEscape), () => {
    onEscapeRef.current?.();
  });

  useEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    if (!container) return;

    // Focus may already be inside: a field with `autoFocus` takes it during
    // the commit, before this effect runs. Unless a start was named
    // explicitly, that is the dialog's own choice and it stands - and the
    // element that had focus before is then the one seen at first render,
    // not the field that has just taken it.
    const alreadyInside = container.contains(document.activeElement);
    previousFocusRef.current = (alreadyInside ? focusAtMount : document.activeElement) as HTMLElement | null;
    const requested = initialFocusRef?.current ?? null;
    if (requested || !alreadyInside) {
      initialFocus(container, requested);
    }

    const layer: TabLayer = { container };
    tabStack.push(layer);
    bindDocumentListener();
    return () => {
      const index = tabStack.lastIndexOf(layer);
      if (index >= 0) tabStack.splice(index, 1);
      unbindDocumentListenerIfIdle();
      previousFocusRef.current?.focus();
    };
  }, [active, containerRef, initialFocusRef, focusAtMount]);
}
