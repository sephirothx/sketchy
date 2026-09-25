import { useLayoutEffect, useRef, type ReactNode } from "react";
import { BulbIcon, ClockIcon, DeckIcon, RoundsIcon, TrophyIcon, UsersIcon } from "./icons";
import { columnsFor, otherRoomRules, roomFacts, type RoomFactKey, type RoomFactsInput } from "../lib/roomCardFacts";
import { textWidth } from "../lib/textWidth";
import { ui } from "../content/ui/index.ts";

const ICONS: Record<RoomFactKey, ReactNode> = {
  players: <UsersIcon size={18} />,
  rounds: <RoundsIcon size={18} />,
  "drawing-time": <ClockIcon size={18} />,
  scoring: <TrophyIcon size={18} />,
  hints: <BulbIcon size={18} />,
  prompts: <DeckIcon size={18} />,
};

/** The widest single word in the strip, values and labels, in its own font:
    what a cell has to hold for no word to break inside itself. */
function widestWord(dl: HTMLElement): number {
  let widest = 0;
  for (const el of dl.querySelectorAll<HTMLElement>(".room-fact-text, .room-fact-label")) {
    for (const word of (el.textContent ?? "").split(/\s+/)) {
      widest = Math.max(widest, textWidth(word, el));
    }
  }
  return widest;
}

/** A cell's horizontal padding. */
function cellPadding(dl: HTMLElement): number {
  const cell = dl.querySelector<HTMLElement>(".room-fact");
  if (!cell) return 0;
  const style = getComputedStyle(cell);
  return parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
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
    // The words are measured once per set of words (and again once the font
    // has loaded); a resize only divides the strip's new width by them.
    let widest = 0;
    let padding = 0;
    const measure = () => {
      widest = widestWord(dl);
      padding = cellPadding(dl);
    };
    const fit = () => {
      const current = dl.dataset.columns ? Number(dl.dataset.columns) : undefined;
      dl.dataset.columns = String(columnsFor(dl.clientWidth, widest, padding, current));
    };
    // Before the first paint, and again once the font has loaded.
    measure();
    fit();
    let live = true;
    void document.fonts?.ready.then(() => {
      if (!live) return;
      measure();
      fit();
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
