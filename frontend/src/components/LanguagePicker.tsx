import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { CheckIcon, ChevronDownIcon, Flag, GlobeIcon } from "./icons";
import {
  promptLanguageEndonym,
  promptLanguageLabel,
} from "../lib/promptLanguages";
import { getFocusableElements, useEscapeLayer } from "../hooks/useFocusTrap";
import type { PromptLanguage } from "../types";

/** The lobby's filter adds "every language" to the same list of choices. */
export const ANY_LANGUAGE = "all";

export type LanguageChoice = PromptLanguage | typeof ANY_LANGUAGE;

interface LanguagePickerProps {
  label: string;
  value: LanguageChoice;
  options: readonly PromptLanguage[];
  onChange: (value: LanguageChoice) => void;
  /** The lobby filters by language; a room picks one, and cannot pick "any". */
  includeAny?: boolean;
  disabled?: boolean;
  /** Sizes the trigger where it sits in a filter bar rather than in a form. */
  compact?: boolean;
  /** Trigger shows the flag alone; the list still names every language. */
  flagOnly?: boolean;
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
 * The English name rides along for screen readers, since the interface around
 * it is English and untranslated.
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
  if (choices.length < 2) {
    return (
      <span className="language-picker-static">
        <LanguageFace value={value} />
      </span>
    );
  }

  return (
    <div
      className={`language-picker${compact ? " is-compact" : ""}${flagOnly ? " is-flag-only" : ""}`}
      ref={rootRef}
    >
      <button
        ref={triggerRef}
        type="button"
        className="language-picker-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`${label}: ${accessibleName(value)}`}
        title={flagOnly ? `${label}: ${accessibleName(value)}` : undefined}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <LanguageFace value={value} nameHidden={flagOnly} fill={flagOnly} />
        {!flagOnly && <ChevronDownIcon size={14} />}
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
          Every language
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
      {/* The interface is English and untranslated, so the English name is
          what makes the row answerable to a screen reader — but only where it
          says something the endonym does not. */}
      {english !== endonym && <span className="visually-hidden">{english}</span>}
    </span>
  );
}

function accessibleName(value: LanguageChoice): string {
  if (value === ANY_LANGUAGE) return "Every language";
  const endonym = promptLanguageEndonym(value);
  const english = promptLanguageLabel(value);
  return english === endonym ? endonym : `${endonym} (${english})`;
}
