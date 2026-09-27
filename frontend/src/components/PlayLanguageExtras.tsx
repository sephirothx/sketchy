import { useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import { LanguageFace, LanguagePicker } from "./LanguagePicker";
import { ChevronDownIcon, ChevronUpIcon, GripIcon, PlusIcon, XIcon } from "./icons";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import { moveExtraPromptLanguage } from "../lib/playLanguages";
import { promptLanguageEndonym, SUPPORTED_PROMPT_LANGUAGES } from "../lib/promptLanguages";
import type { PromptLanguage } from "../types";
import { ui } from "../content/ui/index.ts";

/** How far a handle travels before a press becomes a drag, so a tap on it
never lifts anything. */
const DRAG_THRESHOLD_PX = 4;
/** How long neighbours take to make room and a chip to settle: long enough
to read as movement, short enough never to wait on it. */
// Not copy: a CSS transition - the theme's travelling speed, eased out.
const SETTLE = "translate var(--dur) cubic-bezier(0.25, 1, 0.5, 1)";

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

interface Drag {
  language: PromptLanguage;
  pointerId: number;
  from: number;
  to: number;
  moving: boolean;
  /** The pointer's y when the drag began, in the list's own coordinates, so
  a pane scrolled mid-drag moves the list and the pointer alike. */
  startY: number;
  /** Each chip's top and height when the drag began, in the same terms. */
  slots: { top: number; height: number }[];
}

/**
 * The other languages a player plays in (#1210), stacked in the order they
 * ranked them - the order the lobby ranks those rooms in (#1211) and the
 * profile shows their flags in (#1212).
 *
 * Two ways to reorder, because either alone leaves somebody out. A chip's
 * grip can be dragged with a mouse, a pen or a finger; and each chip has
 * up/down buttons, which a keyboard and a screen reader use and which say
 * where the chip went (WCAG 2.5.7's single-pointer alternative, and for a
 * list this short a better one than a keyboard grab mode).
 *
 * The drag follows the published patterns (Atlassian's Pragmatic drag and
 * drop, dnd-kit's sortable): only the grip lifts the chip, since the chip
 * holds buttons of its own; the lifted chip follows the pointer on the list's
 * one axis, a little raised; its neighbours slide aside to show where it
 * would land; and on release every chip settles into its new place from
 * where it was drawn (FLIP), which the arrow buttons use too. Escape, a
 * cancelled pointer or a lost capture slides everything back. Reduced
 * motion keeps the chip under the pointer and drops the rest of the motion.
 *
 * Positions are written straight to the elements while a drag is held -
 * nothing re-renders per pointer move - and the new order is committed once,
 * on release.
 */
export function PlayLanguageExtras({
  defaultLanguage,
  extras,
  onChange,
}: {
  defaultLanguage: PromptLanguage;
  extras: readonly PromptLanguage[];
  onChange: (next: PromptLanguage[]) => void;
}) {
  const [drag, setDrag] = useState<Drag | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const chipRefs = useRef(new Map<PromptLanguage, HTMLLIElement>());
  const listRef = useRef<HTMLOListElement | null>(null);
  const dragRef = useRef<Drag | null>(null);
  // Where each chip was drawn just before an order was committed, for the
  // settle animation to start from once the new order has been laid out.
  const flipFrom = useRef<Map<PromptLanguage, number> | null>(null);

  const addable = SUPPORTED_PROMPT_LANGUAGES.filter(
    (language) => language !== defaultLanguage && !extras.includes(language),
  );

  function updateDrag(next: Drag | null) {
    dragRef.current = next;
    setDrag(next);
  }

  // Settle: every chip starts where it was drawn and slides to where it now
  // is. Runs after the new order is laid out and before it is painted.
  useLayoutEffect(() => {
    const from = flipFrom.current;
    flipFrom.current = null;
    if (!from || prefersReducedMotion()) return;
    for (const [language, top] of from) {
      const chip = chipRefs.current.get(language);
      if (!chip) continue;
      const delta = top - chip.getBoundingClientRect().top;
      if (Math.abs(delta) < 0.5) continue;
      chip.style.transition = "none";
      chip.style.translate = `0 ${delta}px`;
      // Read back, so the start position is laid out before the transition.
      void chip.offsetHeight;
      chip.style.transition = SETTLE;
      chip.style.translate = "";
    }
  }, [extras]);

  function listTop(): number {
    return listRef.current?.getBoundingClientRect().top ?? 0;
  }

  function clearStyles() {
    for (const chip of chipRefs.current.values()) {
      chip.style.transition = "";
      chip.style.translate = "";
    }
  }

  function commit(next: PromptLanguage[], moved: PromptLanguage, position: number) {
    flipFrom.current = new Map(
      [...chipRefs.current].map(([language, chip]) => [language, chip.getBoundingClientRect().top]),
    );
    clearStyles();
    onChange(next);
    setAnnouncement(
      ui.settingsOverlay.playLanguageMoved({
        name: promptLanguageEndonym(moved),
        position,
        total: next.length,
      }),
    );
  }

  function move(from: number, to: number) {
    if (to < 0 || to >= extras.length || to === from) return;
    commit(moveExtraPromptLanguage(extras, from, to), extras[from], to + 1);
  }

  function moveAndKeepFocus(from: number, to: number, which: "earlier" | "later") {
    const language = extras[from];
    move(from, to);
    // The button pressed may be disabled at the end of the list; the chip's
    // other one keeps the keyboard where it was.
    requestAnimationFrame(() => {
      const chip = chipRefs.current.get(language);
      const target =
        chip?.querySelector<HTMLButtonElement>(`[data-move="${which}"]:not(:disabled)`)
        ?? chip?.querySelector<HTMLButtonElement>("button:not(:disabled)");
      target?.focus();
    });
  }

  function add(language: PromptLanguage) {
    const last = addable.length === 1;
    onChange([...extras, language]);
    // Adding the last language takes the add button away with it: the new
    // chip keeps the keyboard inside the list rather than on the page.
    if (last) {
      requestAnimationFrame(() => {
        chipRefs.current.get(language)?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
      });
    }
  }

  /** Where the dragged chip would land: the place whose centre its own
  centre is nearest, among the places the chips stood in when it began. */
  function slotFor(current: Drag, offset: number): number {
    const own = current.slots[current.from];
    const centre = own.top + own.height / 2 + offset;
    let best = current.from;
    let bestDistance = Number.POSITIVE_INFINITY;
    current.slots.forEach((slot, index) => {
      const distance = Math.abs(slot.top + slot.height / 2 - centre);
      if (distance < bestDistance) {
        best = index;
        bestDistance = distance;
      }
    });
    return best;
  }

  /** Neighbours between where the chip was and where it would land slide one
  place towards the gap it left, so the gap is where it would land. */
  function makeRoom(current: Drag) {
    const { from, to, slots } = current;
    const reduced = prefersReducedMotion();
    extras.forEach((language, index) => {
      if (index === from) return;
      const chip = chipRefs.current.get(language);
      if (!chip) return;
      let shift = 0;
      const step = slots[from].height + gapBetween(slots);
      if (from < to && index > from && index <= to) shift = -step;
      if (from > to && index < from && index >= to) shift = step;
      chip.style.transition = reduced ? "none" : SETTLE;
      chip.style.translate = shift ? `0 ${shift}px` : "";
    });
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLSpanElement>, index: number) {
    if (!event.isPrimary || event.button !== 0 || dragRef.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const top = listTop();
    const slots = extras.map((language) => {
      const box = chipRefs.current.get(language)?.getBoundingClientRect();
      return { top: (box?.top ?? 0) - top, height: box?.height ?? 0 };
    });
    updateDrag({
      language: extras[index],
      pointerId: event.pointerId,
      from: index,
      to: index,
      moving: false,
      startY: event.clientY - top,
      slots,
    });
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLSpanElement>) {
    const current = dragRef.current;
    if (!current || event.pointerId !== current.pointerId) return;
    const first = current.slots[0];
    const last = current.slots[current.slots.length - 1];
    const own = current.slots[current.from];
    // Along the list only, and never past its ends.
    const offset = Math.max(
      first.top - own.top,
      Math.min(last.top + last.height - own.top - own.height, event.clientY - listTop() - current.startY),
    );
    if (!current.moving && Math.abs(offset) < DRAG_THRESHOLD_PX) return;
    const chip = chipRefs.current.get(current.language);
    if (chip) {
      chip.style.transition = "none";
      chip.style.translate = `0 ${offset}px`;
    }
    const to = slotFor(current, offset);
    if (!current.moving || to !== current.to) {
      const next = { ...current, moving: true, to };
      updateDrag(next);
      makeRoom(next);
    }
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLSpanElement>) {
    const current = dragRef.current;
    if (!current || event.pointerId !== current.pointerId) return;
    updateDrag(null);
    if (!current.moving) return;
    if (current.to === current.from) {
      settleBack();
      return;
    }
    commit(
      moveExtraPromptLanguage(extras, current.from, current.to),
      current.language,
      current.to + 1,
    );
  }

  /** Everything slides back to where it was; nothing is committed. */
  function settleBack() {
    const reduced = prefersReducedMotion();
    for (const chip of chipRefs.current.values()) {
      chip.style.transition = reduced ? "none" : SETTLE;
      chip.style.translate = "";
    }
  }

  function cancel() {
    if (!dragRef.current) return;
    updateDrag(null);
    settleBack();
  }

  function cancelDrag(event: ReactPointerEvent<HTMLSpanElement>) {
    if (dragRef.current?.pointerId === event.pointerId) cancel();
  }

  // A drag answers Escape before the dialog it is in does.
  useEscapeLayer(Boolean(drag?.moving), cancel);

  const lifted = drag?.moving ? drag.language : null;
  // The places the chips would have if it were let go now, for their numbers.
  const preview = drag?.moving ? moveExtraPromptLanguage(extras, drag.from, drag.to) : extras;

  return (
    <div className="play-language-extras">
      {extras.length > 0 && (
        <ol
          ref={listRef}
          className={`play-language-extras-list${lifted ? " is-dragging" : ""}`}
          aria-label={ui.settingsOverlay.alsoPlayIn}
        >
          {extras.map((language, index) => {
            const name = promptLanguageEndonym(language);
            return (
              <li
                key={language}
                ref={(element) => {
                  if (element) chipRefs.current.set(language, element);
                  else chipRefs.current.delete(language);
                }}
                className={`play-language-chip${lifted === language ? " is-lifted" : ""}`}
                data-language={language}
              >
                {/* The pointer's way to move it; the buttons are everyone
                    else's, so the grip is not a stop of its own. */}
                <span
                  className="play-language-chip-handle"
                  aria-hidden="true"
                  onPointerDown={(event) => handlePointerDown(event, index)}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  onPointerCancel={cancelDrag}
                  onLostPointerCapture={cancelDrag}
                >
                  <GripIcon size={16} />
                </span>
                <span className="play-language-chip-position" aria-hidden="true">
                  {preview.indexOf(language) + 1}
                </span>
                <LanguageFace value={language} flagWidth={18} />
                <span className="play-language-chip-actions">
                  <button
                    type="button"
                    className="play-language-chip-button"
                    data-move="earlier"
                    aria-label={ui.settingsOverlay.movePlayLanguageEarlier({ name })}
                    disabled={index === 0}
                    onClick={() => moveAndKeepFocus(index, index - 1, "earlier")}
                  >
                    <ChevronUpIcon size={14} />
                  </button>
                  <button
                    type="button"
                    className="play-language-chip-button"
                    data-move="later"
                    aria-label={ui.settingsOverlay.movePlayLanguageLater({ name })}
                    disabled={index === extras.length - 1}
                    onClick={() => moveAndKeepFocus(index, index + 1, "later")}
                  >
                    <ChevronDownIcon size={14} />
                  </button>
                  <button
                    type="button"
                    className="play-language-chip-button"
                    aria-label={ui.settingsOverlay.removePlayLanguage({ name })}
                    onClick={() => onChange(extras.filter((item) => item !== language))}
                  >
                    <XIcon size={14} />
                  </button>
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {addable.length > 0 && (
        <LanguagePicker
          label={ui.settingsOverlay.addPlayLanguage}
          addLabel={ui.settingsOverlay.addPlayLanguageButton}
          options={addable}
          onChange={(next) => add(next as PromptLanguage)}
        />
      )}
      <span className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </span>
    </div>
  );
}

/** The space between two stacked chips, read off where they stood. */
function gapBetween(slots: Drag["slots"]): number {
  if (slots.length < 2) return 0;
  return Math.max(0, slots[1].top - slots[0].top - slots[0].height);
}

/** The browser's other languages, offered as others - never added for the
player, since a browser lists English as a fallback for plenty of people who
could not play a round in it. "Not now" puts them away for this browser. */
export function PlayLanguageSuggestions({
  suggestions,
  onAdd,
  onDismiss,
}: {
  suggestions: readonly PromptLanguage[];
  onAdd: (language: PromptLanguage) => void;
  onDismiss: () => void;
}) {
  if (suggestions.length === 0) return null;
  return (
    <span className="play-language-suggestions">
      <span className="play-language-suggestions-label">
        {ui.settingsOverlay.yourBrowserAlsoReads}
      </span>
      {suggestions.map((language) => (
        <button
          key={language}
          type="button"
          className="toggle-chip play-language-suggestion"
          aria-label={ui.settingsOverlay.addSuggestedPlayLanguage({
            name: promptLanguageEndonym(language),
          })}
          onClick={() => onAdd(language)}
        >
          <PlusIcon size={13} />
          <LanguageFace value={language} flagWidth={16} />
        </button>
      ))}
      <button type="button" className="btn btn-ghost btn-compact" onClick={onDismiss}>
        {ui.settingsOverlay.notNow}
      </button>
    </span>
  );
}
