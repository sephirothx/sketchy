import { useEffect } from "react";
import { useRoomAnnouncer } from "../hooks/useRoomAnnouncement";

/** The phase in a sentence - "X is drawing." - which the chat log does not
    carry. Always mounted, empty between phases, so a new sentence is a text
    change in a region already on the page rather than a region inserted with
    its text, which screen readers announce unreliably (#1423). */
export function GameAnnouncer({ message }: { message: string }) {
  return (
    <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-testid="game-announcer">
      {message}
    </div>
  );
}

/** The room's one live region for what a card says as it appears - the turn
    results, the game over, the drawer's turn (#1423) - via
    `useRoomAnnouncement`. Mounted with the room, so it is on the page before
    anything is said in it. */
export function RoomAnnouncer() {
  const sentence = useRoomAnnouncer((state) => state.sentence);
  const clear = useRoomAnnouncer((state) => state.clear);
  useEffect(() => clear, [clear]);
  return (
    <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-testid="room-announcer">
      {sentence}
    </div>
  );
}
