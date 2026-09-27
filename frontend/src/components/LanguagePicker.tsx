import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { AnyLanguageIcon, CheckIcon, ChevronDownIcon, Flag, GlobeIcon, PlusIcon } from "./icons";
import {
  AGNOSTIC_PROMPT_LANGUAGE,
  MIXED_PROMPT_LANGUAGE,
  promptLanguageEndonym,
  promptLanguageLabel,
} from "../lib/promptLanguages";
import { getFocusableElements, useEscapeLayer } from "../hooks/useFocusTrap";
import type { PromptListLanguage, RoomLanguage } from "../types";
import { ui } from "../content/ui/index.ts";

/** The lobby's filter adds "every language" to the same list of choices. */
export const ANY_LANGUAGE = "all";

/** A list may also be in no language (`zxx`, #821); a room may not, so only a
list's own picker offers it. */
export type LanguageChoice = PromptListLanguage | RoomLanguage | typeof ANY_LANGUAGE;

interface LanguagePickerProps {
  label: string;
  /** None when the picker adds a language rather than choosing one. */
  value?: LanguageChoice;
  options: readonly (PromptListLanguage | RoomLanguage)[];
  onChange: (value: LanguageChoice) => void;
  /** The lobby filters by language; a room picks one, and cannot pick "any". */
  includeAny?: boolean;
  disabled?: boolean;
  /** Sizes the trigger where it sits in a filter bar rather than in a form. */
  compact?: boolean;
  /** Trigger shows the flag alone; the list still names every language. */
  flagOnly?: boolean;
  /** A flag a size down, to sit among a header's buttons rather than a form's rows. */
  small?: boolean;
  /** Adds one of `options` rather than choosing among them (#1210): the
      trigger is a "+ Add" button naming this, and no row is the current one. */
  addLabel?: string;
}

/**
 * Choosing a language, in the one place a language is ever chosen.
 *
 * A native `<select>` was the wrong control here twice over. Its popup is the
 * platform's, so the flags and the endonyms — the two things that let someone
 * find their own language without reading English — stop at the closed field
 * and never reach the list. And the popup is the only part of this interface
 * drawn by the operating system rather than by the game, which is exactly the
 * seam the redesign spent its effort removing.
 *
 * So this is the room menu's mechanism (`LobbyPlayerMenu`) wearing the setup
 * form's clothes (`toggle-chip`): one trigger, arrow keys through the list,
 * Escape closes and hands focus back. Each row is a flag and the language's
 * name as that language writes it — `Deutsch`, not `German` — because the
 * person looking for it is, by definition, looking for the word they use.
 * The name in the reader's own interface language rides along for screen
 * readers, where it says something the endonym does not.
 */
export function LanguagePicker({
  label,
  value,
  options,
  onChange,
  includeAny = false,
  disabled = false,
  compact = false,
  flagOnly = false,
  small = false,
  addLabel,
}: LanguagePickerProps) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEscapeLayer(open, () => {
    setOpen(false);
    triggerRef.current?.focus();
  });

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
      const width = Math.max(list.offsetWidth, trigger.width);
      const natural = list.scrollHeight;
      const below = viewportHeight - trigger.bottom - gap - margin;
      const above = trigger.top - gap - margin;
      const upward = natural > below && above > below;
      let left = trigger.left;
      if (left + width > viewportWidth - margin) left = trigger.right - width;
      left = Math.max(margin, Math.min(left, viewportWidth - margin - width));
      Object.assign(list.style, {
        position: "fixed",
        left: `${left}px`,
        right: "auto",
        minWidth: `${trigger.width}px`,
        maxHeight: `${Math.max(120, Math.min(360, upward ? above : below))}px`,
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
  }, [open]);

  // The chosen row takes focus on open, so the list starts where the reader
  // already is rather than at the top of seven.
  useEffect(() => {
    if (!open || !listRef.current) return;
    const selected = listRef.current.querySelector<HTMLElement>('[aria-selected="true"]');
    (selected ?? getFocusableElements(listRef.current)[0])?.focus();
  }, [open]);

  function choose(next: LanguageChoice) {
    onChange(next);
    setOpen(false);
    triggerRef.current?.focus();
  }

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

  const choices: LanguageChoice[] = includeAny ? [ANY_LANGUAGE, ...options] : [...options];

  // One choice is not a choice: before the other six languages had content,
  // this was a dropdown that could only ever answer "English". It says what
  // the language is instead, in the same face the list would have shown.
  // Adding one is still a choice, of whether to.
  if (choices.length < 2 && addLabel === undefined && value !== undefined) {
    return (
      <span className="language-picker-static">
        <LanguageFace value={value} />
      </span>
    );
  }

  return (
    <div
      className={`language-picker${compact ? " is-compact" : ""}${flagOnly ? " is-flag-only" : ""}${small ? " is-small" : ""}`}
      ref={rootRef}
    >
      <button
        ref={triggerRef}
        type="button"
        className="language-picker-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={
          value === undefined
            ? label
            : ui.languagePicker.currentChoice({ label, value: accessibleName(value) })
        }
        title={flagOnly && value !== undefined ? `${label}: ${accessibleName(value)}` : undefined}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        {value === undefined ? (
          <span className="language-picker-add">
            <PlusIcon size={14} />
            {addLabel}
          </span>
        ) : (
          <>
            <LanguageFace value={value} nameHidden={flagOnly} fill={flagOnly} />
            {!flagOnly && <ChevronDownIcon size={14} />}
          </>
        )}
      </button>

      {open && (
        <div
          id={listId}
          ref={listRef}
          className="language-picker-list"
          role="listbox"
          aria-label={label}
          onKeyDown={handleListKeyDown}
        >
          {choices.map((choice) => {
            const selected = choice === value;
            return (
              <button
                key={choice}
                type="button"
                role="option"
                aria-selected={selected}
                data-language={choice}
                className={`language-picker-option${selected ? " is-selected" : ""}`}
                onClick={() => choose(choice)}
              >
                <LanguageFace value={choice} />
                <span className="language-picker-check" aria-hidden="true">
                  {selected && <CheckIcon size={13} />}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * A language as it is shown wherever it is shown: its flag, then its own name
 * for itself. Read-only surfaces use it too, so a room that cannot change its
 * language still looks like the control that set it.
 */
export function LanguageFace({
  value,
  nameHidden = false,
  flagWidth = 18,
  fill = false,
}: {
  value: LanguageChoice;
  nameHidden?: boolean;
  flagWidth?: number;
  fill?: boolean;
}) {
  if (value === ANY_LANGUAGE) {
    return (
      <span className="language-picker-face">
        <span className="language-picker-flag" aria-hidden="true">
          <GlobeIcon size={Math.round(flagWidth * 0.85)} />
        </span>
        <span className={nameHidden ? "visually-hidden" : "language-picker-name"}>
          {ui.languagePicker.everyLanguage}
        </span>
      </span>
    );
  }
  if (value === AGNOSTIC_PROMPT_LANGUAGE) {
    return (
      <span className="language-picker-face">
        <span className="language-picker-flag" aria-hidden="true">
          <AnyLanguageIcon size={Math.round(flagWidth * 0.85)} />
        </span>
        <span className={nameHidden ? "visually-hidden" : "language-picker-name"}>
          {ui.languagePicker.anyLanguage}
        </span>
      </span>
    );
  }
  const endonym = promptLanguageEndonym(value);
  const english = promptLanguageLabel(value);
  return (
    <span className="language-picker-face">
      <span className="language-picker-flag" aria-hidden="true">
        <Flag language={value} width={flagWidth} fill={fill} />
      </span>
      <span className={nameHidden ? "visually-hidden" : "language-picker-name"}>
        {endonym}
      </span>
      {/* The name in the reader's interface language is what makes the row
          answerable to a screen reader — but only where it says something
          the endonym does not. */}
      {english !== endonym && <span className="visually-hidden">{english}</span>}
    </span>
  );
}

function accessibleName(value: LanguageChoice): string {
  if (value === ANY_LANGUAGE) return ui.languagePicker.everyLanguage;
  if (value === AGNOSTIC_PROMPT_LANGUAGE) return ui.languagePicker.anyLanguage;
  if (value === MIXED_PROMPT_LANGUAGE) return ui.languagePicker.mixed;
  const endonym = promptLanguageEndonym(value);
  const english = promptLanguageLabel(value);
  return english === endonym ? endonym : `${endonym} (${english})`;
}
