import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { CheckIcon, PencilIcon, PlusIcon, XIcon } from "./icons";
import { getFocusableElements, useEscapeLayer } from "../hooks/useFocusTrap";
import type { PromptTag } from "../types";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/prompt-lists.css";

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
 * A list's tags: the ones it carries, and a panel for choosing them.
 *
 * The whole vocabulary used to stand open as chips in a bordered box that took
 * more of the editor than the name, the description and the language together
 * - for a handful of choices made once. Now only the chosen tags stay on
 * screen, and the vocabulary opens on request.
 *
 * Three things are placed so that nothing moves or gets cut off:
 * - The button lives on the label's line, beside the count, so it does not
 *   travel as chips wrap. When it wrapped with them it could land against
 *   the pane's right edge, and a menu hung from it ran off the pane, which
 *   scrolls and so clips.
 * - The panel hangs from the whole field, spanning its width, so whatever
 *   the button does it has the room the field has.
 * - The panel holds chips, the form's own control for choosing several
 *   things out of a fixed set, so a tag looks the same chosen or not.
 */
export function TagPicker({ vocabulary, chosen, max, onChange, nameOf }: TagPickerProps) {
  const labelId = useId();
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const full = chosen.length >= max;

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEscapeLayer(open, close);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  useEffect(() => {
    if (open && panelRef.current) getFocusableElements(panelRef.current)[0]?.focus();
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

  // The chips read left to right and wrap, so every arrow steps through them
  // in reading order - there is no reliable "row above" in a wrapped line.
  function handlePanelKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = panelRef.current ? getFocusableElements(panelRef.current) : [];
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    const moves: Record<string, number> = {
      ArrowRight: (index + 1) % items.length,
      ArrowDown: (index + 1) % items.length,
      ArrowLeft: (index - 1 + items.length) % items.length,
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
    <div className="tag-picker" ref={rootRef}>
      <div className="tag-picker-head">
        <span id={labelId} className="prompt-list-field-label">{ui.myPromptListsPage.tags}</span>
        <span className={full ? "tag-picker-count is-full" : "tag-picker-count"}>
          {ui.myPromptListsPage.tagsChosen({ chosen: chosen.length, max })}
        </span>
        {/* At the cap there is nothing left to add, so it says what it still
            does: the panel is where one tag is swapped for another. Never
            disabled, so Escape always has this button to hand focus back to. */}
        <button
          ref={triggerRef}
          type="button"
          className="tag-picker-trigger"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          onClick={() => (open ? close() : setOpen(true))}
        >
          {full
            ? <><PencilIcon size={12} />{ui.myPromptListsPage.changeTags}</>
            : <><PlusIcon size={12} />{ui.myPromptListsPage.addTag}</>}
        </button>
      </div>
      {chosen.length > 0 && <div className="tag-picker-row">
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
      </div>}
      {open && (
        <div
          id={panelId}
          ref={panelRef}
          className="tag-picker-panel"
          role="group"
          aria-labelledby={labelId}
          onKeyDown={handlePanelKeyDown}
        >
          <div className="tag-picker-options">
            {vocabulary.map((tag) => {
              const held = chosen.includes(tag.slug);
              return (
                <button
                  key={tag.slug}
                  type="button"
                  className={held ? "toggle-chip is-selected" : "toggle-chip"}
                  aria-pressed={held}
                  // At the cap the rest go quiet rather than disappearing:
                  // the vocabulary is the same either way, and a set that
                  // shrinks as you pick from it cannot be read.
                  disabled={!held && full}
                  onClick={() => toggle(tag.slug)}
                >
                  {held && <span className="toggle-chip-status" aria-hidden="true"><CheckIcon size={12} /></span>}
                  <span className="toggle-chip-name">{nameOf(tag)}</span>
                </button>
              );
            })}
          </div>
          <div className="tag-picker-panel-foot">
            <button type="button" className="btn btn-secondary btn-compact" onClick={close}>
              {ui.myPromptListsPage.tagsDone}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
