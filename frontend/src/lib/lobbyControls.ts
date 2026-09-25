/** What the lobby offers, decided from what it knows (R-UX-16, R-UX-17).

Pure and free of runtime imports, so `frontend/tests` can reach the rules
without rendering the page. */

/** How many open rooms it takes before the list offers search and filters.
    With one room open a phone showed a search field, a Filters button and
    "Showing 1 of 1" above a list that fit on the screen: three controls with
    nothing to act on. Six is about where the list runs past a phone's first
    screen, and where finding one room by name starts to beat reading. */
export const ROOM_FILTERS_FROM = 6;

/** Whether the search box and the filters are on screen.

Once shown they stay for the life of the page (`alreadyShown`): the list is
live and changes every second, and a box that came and went with the count
would unmount under a player typing in it - backspacing a query to empty with
five rooms open would take the field away mid-keystroke. A search or a filter
that is on keeps them too, or a list a filter took below the threshold would
hide the very control that widens it again. */
export function showsRoomFilters(state: {
  roomCount: number;
  narrowing: boolean;
  alreadyShown: boolean;
}): boolean {
  return state.alreadyShown || state.narrowing || state.roomCount >= ROOM_FILTERS_FROM;
}

/** Whether the room list's count says anything the list does not: only when a
    filter left rooms out. "0 rooms" beside "No public rooms yet", and "Showing
    1 of 1" above one room, only repeated what was under them. */
export function showsRoomCount(state: { loaded: boolean; shown: number; total: number }): boolean {
  return state.loaded && state.shown < state.total;
}

/** Whether the header's site links lead to the Gallery: only with a session, since
    without one the Gallery is a refusal rather than a page (R-GAL-02). A guest
    has a session; a visitor who has not chosen a name has none. */
export function linksToGallery(user: unknown): boolean {
  return user !== null && user !== undefined;
}
