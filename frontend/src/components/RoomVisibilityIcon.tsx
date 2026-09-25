import { GlobeIcon, LockIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

/**
 * Whether a room is a Public room or a Private room, said beside its name: a
 * globe or a lock, muted and sized to the name's text (game-room.css), with
 * the glossary's words as its accessible name and tooltip. It sits wherever
 * the name is printed - the room bar on a desktop, the waiting room's
 * heading where the bar has given the name up - so the fact travels with the
 * name rather than on a status line of its own.
 */
export function RoomVisibilityIcon({ isPublic }: { isPublic: boolean }) {
  const label = isPublic ? ui.roomVisibilityIcon.publicRoom : ui.roomVisibilityIcon.privateRoom;
  return (
    <span className="room-visibility-icon" role="img" aria-label={label} title={label}>
      {isPublic ? <GlobeIcon /> : <LockIcon />}
    </span>
  );
}
