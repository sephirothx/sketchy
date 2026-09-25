import { useLayoutEffect, useRef, type ReactNode } from "react";
import { BulbIcon, ClockIcon, DeckIcon, RoundsIcon, TrophyIcon, UsersIcon } from "./icons";
import { otherRoomRules, roomFacts, type RoomFactKey, type RoomFactsInput } from "../lib/roomCardFacts";
import { ui } from "../content/ui/index.ts";

const ICONS: Record<RoomFactKey, ReactNode> = {
  players: <UsersIcon size={18} />,
  rounds: <RoundsIcon size={18} />,
  "drawing-time": <ClockIcon size={18} />,
  scoring: <TrophyIcon size={18} />,
  hints: <BulbIcon size={18} />,
  prompts: <DeckIcon size={18} />,
};

/** Six to a row, then three, then two: whichever is the most that still
    gives every word its own width. */
const COLUMN_CHOICES = [6, 3, 2] as const;

let measureContext: CanvasRenderingContext2D | null | undefined;

function widestWord(dl: HTMLElement): number {
  measureContext ??= document.createElement("canvas").getContext("2d");
  if (!measureContext) return 0;
  let widest = 0;
  for (const el of dl.querySelectorAll<HTMLElement>(".room-fact-text, .room-fact-label")) {
    const style = getComputedStyle(el);
    measureContext.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    for (const word of (el.textContent ?? "").split(/\s+/)) {
      widest = Math.max(widest, measureContext.measureText(word).width);
    }
  }
  return widest;
}

/**
 * How many cells to a row, so that no word breaks inside itself: "Defau|lt"
 * in six cells of a 340px column, "Zeitgesteu|erte" in three on a German
 * phone. Measured, not a breakpoint, because the widest word is the
 * language's - "Default" fits three to a phone's row where "Zeitgesteuerte"
 * (Timed) and "Niederländisch" (Dutch) need two - and the strip sits in
 * columns of different widths on the waiting room and the invite page.
 */
function fitColumns(dl: HTMLElement): number {
  const cell = dl.querySelector<HTMLElement>(".room-fact");
  if (!cell) return COLUMN_CHOICES[0];
  const style = getComputedStyle(cell);
  // The cell's padding, its 1px rule, and a pixel for canvas-versus-layout
  // rounding.
  const needed = widestWord(dl) + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + 2;
  return COLUMN_CHOICES.find((columns) => dl.clientWidth / columns >= needed) ?? 2;
}

/**
 * A room's six facts as a strip of cells, and what else the host changed
 * (#580). One component for the waiting room and the invite page, so the room
 * somebody follows a link to reads exactly as the room they arrive in: the
 * same six, in the same order, with the same mark on what is unusual.
 *
 * Label before value in the markup, as a definition list wants it; the cell
 * puts the value above the label on screen.
 */
export function RoomFacts({ room, testId = "room-facts" }: { room: RoomFactsInput; testId?: string }) {
  const others = otherRoomRules(room);
  const facts = roomFacts(room);
  const listRef = useRef<HTMLDListElement | null>(null);
  // What the widest word depends on: the words themselves (a language, a
  // changed rule). The width is the observer's.
  const words = facts.map((fact) => `${fact.label}\n${fact.value}`).join("\n");
  useLayoutEffect(() => {
    const dl = listRef.current;
    if (!dl) return;
    const fit = () => {
      dl.dataset.columns = String(fitColumns(dl));
    };
    // Before the first paint, and again once the font has loaded.
    fit();
    let live = true;
    void document.fonts?.ready.then(() => {
      if (live) fit();
    });
    // A later resize waits a frame: the new column count changes the strip's
    // height, which inside the observer's own callback is a loop it reports
    // as an error.
    let frame = 0;
    const resizes = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fit);
    });
    resizes.observe(dl);
    return () => {
      live = false;
      cancelAnimationFrame(frame);
      resizes.disconnect();
    };
  }, [words]);
  return (
    <>
      <dl ref={listRef} className="room-facts" data-testid={testId}>
        {facts.map((fact) => (
          <div
            key={fact.key}
            className={`room-fact${fact.changed ? " is-changed" : ""}`}
            data-fact={fact.key}
          >
            <dt className="room-fact-label">{fact.label}</dt>
            <dd className="room-fact-value">
              <span className="room-fact-icon" aria-hidden="true">{ICONS[fact.key]}</span>
              <span className="room-fact-text">{fact.value}</span>
            </dd>
          </div>
        ))}
      </dl>
      {others.length > 0 && (
        <p className="room-facts-also">
          <span>{ui.roomFacts.also}</span>
          {others.map((rule) => <span key={rule} className="chip chip-primary">{rule}</span>)}
        </p>
      )}
    </>
  );
}
