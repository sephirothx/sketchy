import { useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import { LanguageFace, LanguagePicker } from "./LanguagePicker";
import { ChevronLeftIcon, ChevronRightIcon, XIcon } from "./icons";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import { moveExtraPromptLanguage } from "../lib/playLanguages";
import { promptLanguageEndonym, SUPPORTED_PROMPT_LANGUAGES } from "../lib/promptLanguages";
import type { PromptLanguage } from "../types";
import { ui } from "../content/ui/index.ts";

/** How far a pointer travels before a press on a chip becomes a drag, so a
tap on a phone never reorders anything. */
const DRAG_THRESHOLD_PX = 6;

interface Drag {
  pointerId: number;
  from: number;
  startX: number;
  startY: number;
  moving: boolean;
  to: number;
  /** Where each place in the row was when the drag began, from the row's own
  corner: the target is the nearest of these, so it does not hang on the
  preview having rendered, and a pane scrolled mid-drag moves them with it. */
  slots: { x: number; y: number }[];
}

/**
 * The other languages a player plays in (#1210), as chips in the order they
 * ranked them - the order the lobby ranks those rooms in (#1211) and the
 * profile shows their flags in (#1212).
 *
 * Two ways to reorder, because either alone leaves somebody out: a chip can be
 * dragged with a mouse, a pen or a finger, and each has earlier/later buttons
 * for a keyboard and a screen reader, which also say where it went. A drag
 * shows the order it would make while it is held and commits on release;
 * Escape, a cancelled pointer or a lost capture puts it back.
 *
 * The preview moves chips with CSS `order`, never in the DOM: a browser
 * releases a pointer's capture from a node that is moved, and a drag whose
 * chip was moved forward stopped hearing its own release.
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
  const rowRef = useRef<HTMLDivElement | null>(null);

  function rowOrigin(): { x: number; y: number } {
    const box = rowRef.current?.getBoundingClientRect();
    return { x: box?.left ?? 0, y: box?.top ?? 0 };
  }

  // The order the chips show in: the committed one, or the one a drag would
  // make. Chips stay in `extras` order in the DOM; this only sets their place.
  const shown = drag?.moving ? moveExtraPromptLanguage(extras, drag.from, drag.to) : extras;

  const addable = SUPPORTED_PROMPT_LANGUAGES.filter(
    (language) => language !== defaultLanguage && !extras.includes(language),
  );

  function announceAt(language: PromptLanguage, position: number, total: number) {
    setAnnouncement(
      ui.settingsOverlay.playLanguageMoved({
        name: promptLanguageEndonym(language),
        position,
        total,
      }),
    );
  }

  function move(from: number, to: number) {
    if (to < 0 || to >= extras.length || to === from) return;
    onChange(moveExtraPromptLanguage(extras, from, to));
    announceAt(extras[from], to + 1, extras.length);
  }

  function moveAndKeepFocus(from: number, to: number, which: "earlier" | "later") {
    const language = extras[from];
    move(from, to);
    // The button pressed may be disabled at the end of the row; the chip's
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
    // chip keeps the keyboard inside the row rather than on the page.
    if (last) {
      requestAnimationFrame(() => {
        chipRefs.current.get(language)?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
      });
    }
  }

  /** The place a pointer at (x, y) is over: the nearest of the places the
  chips stood in when the drag began - nearest by centre, since chips wrap
  onto several lines and neither axis alone orders them. */
  function slotAt(slots: Drag["slots"], x: number, y: number): number {
    const origin = rowOrigin();
    let best = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    slots.forEach((slot, position) => {
      const distance = Math.hypot(slot.x - (x - origin.x), slot.y - (y - origin.y));
      if (distance < bestDistance) {
        best = position;
        bestDistance = distance;
      }
    });
    return best;
  }

  // The drag as the handlers read it. Pointer moves are not flushed one by
  // one, so a release can arrive before the last move has rendered; the
  // handlers read and write this, and the state only draws it.
  const dragRef = useRef<Drag | null>(null);

  function updateDrag(next: Drag | null) {
    dragRef.current = next;
    setDrag(next);
  }

  // A drag answers Escape before the dialog it is in does.
  useEscapeLayer(Boolean(drag?.moving), () => updateDrag(null));

  function handlePointerDown(event: ReactPointerEvent<HTMLLIElement>, index: number) {
    if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const origin = rowOrigin();
    const slots = extras.map((language) => {
      const box = chipRefs.current.get(language)?.getBoundingClientRect();
      return box
        ? { x: box.left + box.width / 2 - origin.x, y: box.top + box.height / 2 - origin.y }
        : { x: Number.POSITIVE_INFINITY, y: Number.POSITIVE_INFINITY };
    });
    updateDrag({
      pointerId: event.pointerId,
      from: index,
      to: index,
      startX: event.clientX,
      startY: event.clientY,
      moving: false,
      slots,
    });
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLLIElement>) {
    const current = dragRef.current;
    if (!current || event.pointerId !== current.pointerId) return;
    const moving =
      current.moving
      || Math.hypot(event.clientX - current.startX, event.clientY - current.startY)
        >= DRAG_THRESHOLD_PX;
    if (!moving) return;
    event.preventDefault();
    const to = slotAt(current.slots, event.clientX, event.clientY);
    if (moving !== current.moving || to !== current.to) updateDrag({ ...current, moving, to });
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLLIElement>) {
    const current = dragRef.current;
    if (!current || event.pointerId !== current.pointerId) return;
    updateDrag(null);
    if (current.moving) {
      move(current.from, slotAt(current.slots, event.clientX, event.clientY));
    }
  }

  function cancelDrag(event: ReactPointerEvent<HTMLLIElement>) {
    if (dragRef.current?.pointerId === event.pointerId) updateDrag(null);
  }

  return (
    <div className="play-language-extras" ref={rowRef}>
      {extras.length > 0 && (
        <ol className="play-language-extras-list" aria-label={ui.settingsOverlay.alsoPlayIn}>
          {extras.map((language, domIndex) => {
            const name = promptLanguageEndonym(language);
            const index = shown.indexOf(language);
            const dragging = drag?.moving && drag.from === domIndex;
            return (
              <li
                key={language}
                ref={(element) => {
                  if (element) chipRefs.current.set(language, element);
                  else chipRefs.current.delete(language);
                }}
                className={`play-language-chip${dragging ? " is-dragging" : ""}`}
                data-language={language}
                style={{ order: index }}
                onPointerDown={(event) => handlePointerDown(event, domIndex)}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                onPointerCancel={cancelDrag}
                onLostPointerCapture={cancelDrag}
              >
                <span className="play-language-chip-position" aria-hidden="true">
                  {index + 1}
                </span>
                <LanguageFace value={language} flagWidth={16} />
                <span className="play-language-chip-actions">
                  <button
                    type="button"
                    className="play-language-chip-button"
                    data-move="earlier"
                    aria-label={ui.settingsOverlay.movePlayLanguageEarlier({ name })}
                    disabled={index === 0}
                    onClick={() => moveAndKeepFocus(domIndex, domIndex - 1, "earlier")}
                  >
                    <ChevronLeftIcon size={14} />
                  </button>
                  <button
                    type="button"
                    className="play-language-chip-button"
                    data-move="later"
                    aria-label={ui.settingsOverlay.movePlayLanguageLater({ name })}
                    disabled={index === shown.length - 1}
                    onClick={() => moveAndKeepFocus(domIndex, domIndex + 1, "later")}
                  >
                    <ChevronRightIcon size={14} />
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
