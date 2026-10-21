import { createContext, useContext, useEffect, useMemo, useRef } from "react";

import { createPageHistory, type PageHistory } from "../lib/pageHistory";
import {
  createRoomHistory,
  historyPortFor,
  leaveRoomHistory,
  type RoomHistory,
  type RoomSeat,
} from "../lib/roomHistory";

/** Back in a room (R-UX-15): the React half of `lib/roomHistory.ts`, which
holds the rules and imports nothing so the tests can reach it. */

const RoomHistoryContext = createContext<RoomHistory | null>(null);

/** Provided by the live room only, so a sheet anywhere else - the lobby's, or
one inside the Settings overlay, which draws its own route entry - leaves the
history alone. */
export const RoomHistoryProvider = RoomHistoryContext.Provider;

function browserPort() {
  return historyPortFor(window);
}

/** The room's entries on the history stack, for as long as the room is mounted.
`onBackOnRoom` is what Back from the room itself does: the room's own Leave.
Keyed on the seat as well as the room, so entries pushed for a seat since
given up are never taken for this one's (see `RoomSeat`). */
export function useRoomHistory(
  code: string,
  seat: string,
  onBackOnRoom: () => void,
): RoomHistory {
  const history = useMemo(
    () => createRoomHistory(browserPort(), { code, seat }),
    [code, seat],
  );
  useEffect(() => {
    history.onBackOnRoom(onBackOnRoom);
  });
  useEffect(() => {
    history.start();
    return () => history.stop();
  }, [history]);
  return history;
}

/** Let Back close this surface while `active`, as Escape does.

A no-op outside a room. Inside one, opening pushes an entry on the room's URL
and closing any other way takes it back, so Back always closes what is on top
and never has to walk past something already shut. */
export function useBackCloses(active: boolean, onClose: () => void): void {
  const history = useContext(RoomHistoryContext);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    if (!active || !history) return;
    return history.open(() => onCloseRef.current());
  }, [active, history]);
}

/** The page's layers on the history stack (`lib/pageHistory.ts`), made on
first use: one per window, like the port under it. */
let pageHistory: PageHistory | null = null;

/** Let Back close this layer over a page that is not a room, as Escape does
(R-UX-15): the drawing viewer opened from a profile.

Inside a room it does nothing - the room's own history answers Back there,
through `useBackCloses` - so a surface that can be opened in both calls both.
Layers opened in one render take entries in the order their hooks run, so
the outer one is called first. */
export function usePageBackCloses(active: boolean, onClose: () => void): void {
  const inRoom = useContext(RoomHistoryContext) !== null;
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    if (!active || inRoom) return;
    pageHistory ??= createPageHistory(browserPort());
    return pageHistory.open(() => onCloseRef.current());
  }, [active, inRoom]);
}

/** Leave the room's history the way the room is left: its entries rewound off
the stack, then `finish` navigates - replacing the entry the room was entered
on when `replace` is true, so Back from the lobby does not come back here. */
export function exitRoomHistory(who: RoomSeat, finish: (replace: boolean) => void): void {
  leaveRoomHistory(browserPort(), who, finish);
}
