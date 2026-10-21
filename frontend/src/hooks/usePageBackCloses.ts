import { useEffect, useRef } from "react";

import { createPageHistory, type PageHistory } from "../lib/pageHistory";
import { historyPortFor } from "../lib/roomHistory";
import { useOverlayOpen } from "./useOverlayRoute";
import { useInRoomHistory } from "./useRoomHistory";

/* Apart from `useRoomHistory.ts`, which every page loads: this half rides
with the drawing viewer, the one surface that uses it. */

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
  const inRoom = useInRoomHistory();
  const overlayOpen = useOverlayOpen();
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });
  useEffect(() => {
    if (!active || inRoom) return;
    pageHistory ??= createPageHistory(historyPortFor(window));
    return pageHistory.open(() => onCloseRef.current());
  }, [active, inRoom]);
  // An overlay route opened over the layer: an entry of the router's after
  // theirs, which Forward has to reach once they close.
  useEffect(() => {
    if (active && overlayOpen && !inRoom) pageHistory?.followed();
  }, [active, overlayOpen, inRoom]);
}
