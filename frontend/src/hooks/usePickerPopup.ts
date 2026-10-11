/** The mechanism under every picker: a trigger that opens a floating list.

One hook rather than one per picker, because the behaviour is the same wherever
a choice is made - a report's reason, a filter's period, a room's language -
and it was already written once, for the language picker, with the care the
others deserve: the list is placed in the window rather than in whatever holds
the trigger (a dialog's scrolling body clipped it), Escape closes through the
shared layer stack so a picker over a dialog closes before the dialog does, the
chosen row takes focus on open, and the arrow keys walk the rows. What each
picker draws on the trigger and in the rows is its own. */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, RefObject } from "react";

import { getFocusableElements, useEscapeLayer } from "./useFocusTrap";

interface PickerPopupOptions {
  /** The list hangs from the trigger's right edge rather than its left: for
      a trigger standing at the end of its row. */
  alignEnd?: boolean;
  /** A ref the caller holds on the trigger, when something outside the
      picker needs to focus it (a dialog's initial focus). */
  triggerRef?: RefObject<HTMLButtonElement | null>;
}

export function usePickerPopup({ alignEnd = false, triggerRef: externalTriggerRef }: PickerPopupOptions = {}) {
  const [open, setOpen] = useState(false);
  const ownTriggerRef = useRef<HTMLButtonElement | null>(null);
  const triggerRef = externalTriggerRef ?? ownTriggerRef;
  const listRef = useRef<HTMLDivElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEscapeLayer(open, close);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  // Placed in the window, not in whatever holds the trigger: a picker inside a
  // dialog's scrolling body was clipped by it and scrolled it both ways. Under
  // the trigger where it fits, over it where there is more room above, and
  // held inside the window's edges - its right edge on the trigger's when the
  // trigger sits at the end of a row. Placed before paint, and again as
  // anything scrolls or the window changes size. Written to the list itself,
  // which goes when the list closes.
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const trigger = triggerRef.current?.getBoundingClientRect();
      const list = listRef.current;
      if (!trigger || !list) return;
      const margin = 8;
      const gap = 6;
      const viewportWidth = document.documentElement.clientWidth;
      const viewportHeight = window.innerHeight;
      const below = viewportHeight - trigger.bottom - gap - margin;
      const above = trigger.top - gap - margin;
      // At the height it will have, and only then measured, so its width is
      // the one it is drawn at.
      list.style.top = "0px";
      list.style.left = "0px";
      list.style.right = "auto";
      list.style.bottom = "auto";
      list.style.minWidth = `${Math.min(trigger.width, viewportWidth - 2 * margin)}px`;
      // Never wider than the window: a row's label wraps instead.
      list.style.maxWidth = `${viewportWidth - 2 * margin}px`;
      list.style.maxHeight = "";
      const natural = list.scrollHeight;
      const upward = natural > below && above > below;
      list.style.maxHeight = `${Math.max(120, Math.min(360, upward ? above : below))}px`;
      const width = Math.max(list.offsetWidth, trigger.width);
      let left = alignEnd ? trigger.right - width : trigger.left;
      if (left + width > viewportWidth - margin) left = trigger.right - width;
      left = Math.max(margin, Math.min(left, viewportWidth - margin - width));
      Object.assign(list.style, {
        left: `${left}px`,
        top: upward ? "auto" : `${trigger.bottom + gap}px`,
        bottom: upward ? `${viewportHeight - trigger.top + gap}px` : "auto",
      });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, alignEnd, triggerRef]);

  // The chosen row takes focus on open, so the list starts where the reader
  // already is rather than at the top of it.
  useEffect(() => {
    if (!open || !listRef.current) return;
    const selected = listRef.current.querySelector<HTMLElement>('[aria-selected="true"]');
    (selected ?? getFocusableElements(listRef.current)[0])?.focus();
  }, [open]);

  function handleListKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = listRef.current ? getFocusableElements(listRef.current) : [];
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      items[(index + 1) % items.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      items[(index - 1 + items.length) % items.length]?.focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      items[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      items[items.length - 1]?.focus();
    }
  }

  return {
    open,
    toggle: () => setOpen((current) => !current),
    /** Closes and hands focus back to the trigger: after a choice, or Escape. */
    close,
    triggerRef,
    listRef,
    rootRef,
    handleListKeyDown,
  };
}
