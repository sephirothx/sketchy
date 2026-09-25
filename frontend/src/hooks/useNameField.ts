import { useCallback, useLayoutEffect, useRef, type ChangeEvent } from "react";
import { MAX_NICKNAME_LENGTH, keepNameCharacters, nameCharactersToInsert } from "../lib/roomEntryState";

/** The insertions the browser describes before making them. */
const INSERTIONS = new Set(["insertText", "insertFromPaste", "insertFromDrop", "insertReplacementText"]);

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
 */
export function useNameField(onValue: (value: string) => void) {
  const element = useRef<HTMLInputElement | null>(null);
  const composing = useRef(false);
  const latest = useRef(onValue);
  useLayoutEffect(() => {
    latest.current = onValue;
  });

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
      // Deprecated, and still the one way to insert text that the browser's
      // undo history records, in every engine.
      if (allowed) document.execCommand("insertText", false, allowed);
    };
    const compositionStart = () => {
      composing.current = true;
    };
    const compositionEnd = () => {
      composing.current = false;
      latest.current(cleanUp(field));
    };
    field.addEventListener("beforeinput", beforeInput);
    field.addEventListener("compositionstart", compositionStart);
    field.addEventListener("compositionend", compositionEnd);
    return () => {
      field.removeEventListener("beforeinput", beforeInput);
      field.removeEventListener("compositionstart", compositionStart);
      field.removeEventListener("compositionend", compositionEnd);
    };
  }, []);

  const onChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const field = event.target;
    latest.current(composing.current ? field.value : cleanUp(field));
  }, []);

  return { ref, element, onChange };
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
