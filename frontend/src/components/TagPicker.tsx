import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { CheckIcon, PlusIcon, XIcon } from "./icons";
import { getFocusableElements, useEscapeLayer } from "../hooks/useFocusTrap";
import type { PromptTag } from "../types";
import { ui } from "../content/ui/index.ts";

interface TagPickerProps {
  /** The curated vocabulary, in its own order (R-LIST-18). */
  vocabulary: PromptTag[];
  /** Chosen slugs, in vocabulary order. */
  chosen: string[];
  max: number;
  onChange: (slugs: string[]) => void;
  /** A tag's name in the reader's language. */
  nameOf: (tag: PromptTag) => string;
}

/**
 * A list's tags: the ones it carries, and a menu for the rest.
 *
 * The whole vocabulary used to stand open as chips, fifteen of them in a
 * bordered box that took more of the editor than the name, the description and
 * the language together - for three choices made once. What a list carries is
 * what is read back, so only that stays on screen; the rest is one "Add tag"
 * away. The menu stays open while choosing, because choosing several is the
 * point, and is the language picker's mechanism: arrow keys through it,
 * Escape closes and hands focus back.
 */
export function TagPicker({ vocabulary, chosen, max, onChange, nameOf }: TagPickerProps) {
  const labelId = useId();
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const full = chosen.length >= max;

  useEscapeLayer(open, () => {
    setOpen(false);
    triggerRef.current?.focus();
  });

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  useEffect(() => {
    if (open && menuRef.current) getFocusableElements(menuRef.current)[0]?.focus();
  }, [open]);

  function toggle(slug: string) {
    const held = chosen.includes(slug);
    if (!held && full) return;
    // Vocabulary order, so the chips and the saved list read the same way round.
    onChange(
      vocabulary
        .map((tag) => tag.slug)
        .filter((candidate) => (candidate === slug ? !held : chosen.includes(candidate))),
    );
  }

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = menuRef.current ? getFocusableElements(menuRef.current) : [];
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    const moves: Record<string, number> = {
      ArrowDown: (index + 1) % items.length,
      ArrowUp: (index - 1 + items.length) % items.length,
      Home: 0,
      End: items.length - 1,
    };
    if (event.key in moves) {
      event.preventDefault();
      items[moves[event.key]]?.focus();
    }
  }

  const bySlug = new Map(vocabulary.map((tag) => [tag.slug, tag]));

  return (
    <div className="tag-picker" role="group" aria-labelledby={labelId}>
      <span id={labelId} className="prompt-list-field-label">{ui.myPromptListsPage.tags}</span>
      <div className="tag-picker-row">
        {chosen.map((slug) => {
          const tag = bySlug.get(slug);
          if (!tag) return null;
          return (
            <span key={slug} className="tag-picker-chip">
              <span>{nameOf(tag)}</span>
              <button
                type="button"
                className="tag-picker-remove"
                aria-label={ui.myPromptListsPage.removeTag({ tag: nameOf(tag) })}
                onClick={() => toggle(slug)}
              ><XIcon size={12} /></button>
            </span>
          );
        })}
        <div className="tag-picker-add" ref={rootRef}>
          {/* Never disabled, even at the cap: the menu is also where a tag is
              swapped for another, and Escape hands focus back to this button,
              which a disabled button cannot take. At the cap the unchosen rows
              go quiet instead, and the count beside it says why. */}
          <button
            ref={triggerRef}
            type="button"
            className="tag-picker-trigger"
            aria-haspopup="menu"
            aria-expanded={open}
            aria-controls={open ? menuId : undefined}
            title={ui.myPromptListsPage.tagsAreHowListsAreFound}
            onClick={() => setOpen((current) => !current)}
          >
            <PlusIcon size={13} />{ui.myPromptListsPage.addTag}
          </button>
          {open && (
            <div
              id={menuId}
              ref={menuRef}
              className="language-picker-list tag-picker-menu"
              role="menu"
              aria-labelledby={labelId}
              onKeyDown={handleMenuKeyDown}
            >
              {vocabulary.map((tag) => {
                const held = chosen.includes(tag.slug);
                return (
                  <button
                    key={tag.slug}
                    type="button"
                    role="menuitemcheckbox"
                    aria-checked={held}
                    className={`language-picker-option${held ? " is-selected" : ""}`}
                    disabled={!held && full}
                    onClick={() => toggle(tag.slug)}
                  >
                    <span>{nameOf(tag)}</span>
                    <span className="language-picker-check" aria-hidden="true">
                      {held && <CheckIcon size={13} />}
                    </span>
                  </button>
                );
              })}
              <p className="tag-picker-foot">{ui.myPromptListsPage.tagsAreHowListsAreFound}</p>
            </div>
          )}
        </div>
        <span className={full ? "tag-picker-count is-full" : "tag-picker-count"}>
          {ui.myPromptListsPage.tagsChosen({ chosen: chosen.length, max })}
        </span>
      </div>
    </div>
  );
}
