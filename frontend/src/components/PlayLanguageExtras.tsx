import { useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";

import { LanguageFace, LanguagePicker } from "./LanguagePicker";
import { ChevronLeftIcon, ChevronRightIcon, XIcon } from "./icons";
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
 * Escape or a cancelled pointer puts it back.
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
  const chipRefs = useRef<(HTMLLIElement | null)[]>([]);

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
    move(from, to);
    // The button pressed may vanish at the end of the row; the chip's other
    // one, or the chip's first control, keeps the keyboard where it was.
    requestAnimationFrame(() => {
      const chip = chipRefs.current[to];
      const target =
        chip?.querySelector<HTMLButtonElement>(`[data-move="${which}"]:not(:disabled)`)
        ?? chip?.querySelector<HTMLButtonElement>("button:not(:disabled)");
      target?.focus();
    });
  }

  /** The slot a pointer at (x, y) is over: the chip whose centre is nearest,
  since chips wrap onto several lines and neither axis alone orders them. */
  function slotAt(x: number, y: number): number {
    let best = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    chipRefs.current.forEach((chip, index) => {
      if (!chip) return;
      const box = chip.getBoundingClientRect();
      const distance = Math.hypot(box.left + box.width / 2 - x, box.top + box.height / 2 - y);
      if (distance < bestDistance) {
        best = index;
        bestDistance = distance;
      }
    });
    return best;
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLLIElement>, index: number) {
    if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({
      pointerId: event.pointerId,
      from: index,
      to: index,
      startX: event.clientX,
      startY: event.clientY,
      moving: false,
    });
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLLIElement>) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const moving =
      drag.moving
      || Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) >= DRAG_THRESHOLD_PX;
    if (!moving) return;
    event.preventDefault();
    const to = slotAt(event.clientX, event.clientY);
    if (moving !== drag.moving || to !== drag.to) setDrag({ ...drag, moving, to });
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLLIElement>) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    setDrag(null);
    if (drag.moving) move(drag.from, drag.to);
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLOListElement>) {
    if (event.key === "Escape" && drag) {
      event.stopPropagation();
      setDrag(null);
    }
  }

  return (
    <div className="play-language-extras">
      {extras.length > 0 && (
        <ol
          className="play-language-extras-list"
          aria-label={ui.settingsOverlay.alsoPlayIn}
          onKeyDown={handleKeyDown}
        >
          {shown.map((language, index) => {
            const name = promptLanguageEndonym(language);
            const dragging = drag?.moving && drag.to === index;
            return (
              <li
                key={language}
                ref={(element) => {
                  chipRefs.current[index] = element;
                }}
                className={`play-language-chip${dragging ? " is-dragging" : ""}`}
                data-language={language}
                onPointerDown={(event) => handlePointerDown(event, index)}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                onPointerCancel={() => setDrag(null)}
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
                    onClick={() => moveAndKeepFocus(index, index - 1, "earlier")}
                  >
                    <ChevronLeftIcon size={14} />
                  </button>
                  <button
                    type="button"
                    className="play-language-chip-button"
                    data-move="later"
                    aria-label={ui.settingsOverlay.movePlayLanguageLater({ name })}
                    disabled={index === shown.length - 1}
                    onClick={() => moveAndKeepFocus(index, index + 1, "later")}
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
          onChange={(next) => onChange([...extras, next as PromptLanguage])}
        />
      )}
      <span className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </span>
    </div>
  );
}
