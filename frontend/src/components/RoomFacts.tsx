import type { ReactNode } from "react";
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
  return (
    <>
      <dl className="room-facts" data-testid={testId}>
        {roomFacts(room).map((fact) => (
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
