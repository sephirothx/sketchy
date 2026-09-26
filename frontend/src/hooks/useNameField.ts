import { useCallback, useLayoutEffect, useRef, useState, type ChangeEvent } from "react";
import { MAX_NICKNAME_LENGTH, keepNameCharacters, nameCharactersToInsert } from "../lib/roomEntryState";
import { useToast } from "../lib/toast";

/** The insertions the browser describes before making them, at the selection.
    Not `insertReplacementText` (a spelling or autocorrect replacement): its
    target range is not the selection, so inserting there would put the text
    in the wrong place; the `onChange` clean-up handles it instead. */
const INSERTIONS = new Set(["insertText", "insertFromPaste", "insertFromDrop"]);

/**
 * A name field that only ever holds the name rule's characters: letters,
 * digits, `_` and `-`, at most `MAX_NICKNAME_LENGTH` (R-UX-13). The first-run
 * name tag and the invite page's name field both use it, so the two behave
 * alike.
 *
 * The work is done before the browser inserts anything, on the native
 * `beforeinput` (React's `onBeforeInput` is a synthetic keypress-based event
 * that does not carry pastes and drops): a key, paste or drop with a refused
 * character in it is cancelled, and whatever of it is allowed is inserted
 * with `execCommand("insertText")` instead. That way a refused key simply
 * does nothing - a selection it would have replaced is left alone - and the
 * browser's own undo and redo keep working, since every change is still one
 * the browser made. Rewriting `field.value` afterwards, which this replaced,
 * broke undo in all three engines and let WebKit's redo triple the name.
 *
 * What `beforeinput` does not cover - an input method's composition, which
 * must not be fought mid-word, and anything a browser inserts without asking -
 * is cleaned up after the fact by `onChange`, the caret kept in place: while
 * composing the text is left alone, and what the composition commits is
 * filtered at `compositionend`.
 *
 * `onValue` is told the field's value after every change, already clean.
 *
 * A refused name is the field's too: `refuse(message)` says why in a toast
 * and sets `refused` - for `aria-invalid` and the red line - until the next
 * edit. Never a line in or under the form: one that appeared moved everything
 * below it, and one held empty for it was space for nothing (R-UX-13). On a
 * desktop the focus goes back in the field. With a touch screen it does not:
 * the toast is fixed to the bottom of the layout viewport, and iOS Safari
 * lays the keyboard over that rather than resizing it (it ignores
 * `interactive-widget=resizes-content`), so a refocused field kept the
 * keyboard up and the toast under it - the refusal went unread. There the
 * keyboard is let go, and the red line says which field to tap.
 */
export function useNameField(onValue: (value: string) => void) {
  const element = useRef<HTMLInputElement | null>(null);
  const composing = useRef(false);
  const { notify } = useToast();
  const [refused, setRefused] = useState(false);
  const latest = useRef(onValue);
  useLayoutEffect(() => {
    latest.current = onValue;
  });
  // Every change is reported through here: any edit takes a refusal back.
  const report = useCallback((value: string) => {
    setRefused(false);
    latest.current(value);
  }, []);

  const ref = useCallback((field: HTMLInputElement | null) => {
    element.current = field;
    if (!field) return;
    const beforeInput = (event: InputEvent) => {
      if (event.isComposing || !INSERTIONS.has(event.inputType)) return;
      const data = event.data ?? event.dataTransfer?.getData("text/plain") ?? null;
      if (data === null) return;
      const selected = (field.selectionEnd ?? 0) - (field.selectionStart ?? 0);
      const room = MAX_NICKNAME_LENGTH - (field.value.length - selected);
      const allowed = nameCharactersToInsert(data, room);
      if (allowed === data) return;
      event.preventDefault();
      if (!allowed) return;
      // Deprecated, and still the one way to insert text that the browser's
      // undo history records, in every engine - but it acts on whatever has
      // the focus, so only while this field does.
      if (document.activeElement === field && document.execCommand("insertText", false, allowed)) return;
      // Where it cannot, the text still goes in, at the selection, and the
      // value is reported by hand; that one edit is lost to undo.
      field.setRangeText(allowed, field.selectionStart ?? field.value.length, field.selectionEnd ?? field.value.length, "end");
      report(field.value);
    };
    const compositionStart = () => {
      composing.current = true;
    };
    const compositionEnd = () => {
      composing.current = false;
      report(cleanUp(field));
    };
    field.addEventListener("beforeinput", beforeInput);
    field.addEventListener("compositionstart", compositionStart);
    field.addEventListener("compositionend", compositionEnd);
    return () => {
      field.removeEventListener("beforeinput", beforeInput);
      field.removeEventListener("compositionstart", compositionStart);
      field.removeEventListener("compositionend", compositionEnd);
    };
  }, [report]);

  const onChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const field = event.target;
    report(composing.current ? field.value : cleanUp(field));
  }, [report]);

  const refuse = useCallback((message: string) => {
    setRefused(true);
    notify(message, "error");
    const field = element.current;
    if (!field) return;
    if (window.matchMedia?.("(pointer: coarse)").matches) {
      if (document.activeElement === field) field.blur();
    } else {
      field.focus();
    }
  }, [notify]);

  return { ref, element, onChange, refused, refuse };
}

/** The fallback: correct the field in place, caret included, before React
    compares it with its state - a change that only removed refused characters
    leaves the state as it was, and React would otherwise put the old value
    back with the caret at the end. */
function cleanUp(field: HTMLInputElement): string {
  const next = keepNameCharacters(field.value, field.selectionStart ?? field.value.length);
  if (next.value !== field.value) {
    field.value = next.value;
    field.setSelectionRange(next.caret, next.caret);
  }
  return next.value;
}
