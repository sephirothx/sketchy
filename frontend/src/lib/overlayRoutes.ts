/** The routes that draw *over* the page instead of replacing it.

Settings established the shape (R-SET-06): a real route, so it can be linked,
bookmarked and pointed at from an answer to a support question, rendered
against the location it was opened from, so opening it never unmounts a live
room. Friends needs exactly that and for the same reason - a request can
arrive mid-game, and answering it must not cost a seat (R-FRIEND-10) - so the
mechanism lives here rather than being written a second time beside it.

What is shared is the *background*: one state key, which `App.tsx` reads for
every overlay there is. What each overlay does with its own path is not shared
and stays beside it.

Deliberately free of runtime imports, the same way `friends.ts` is: the tests
run on bare `node:test` with no bundler, so a module that pulls in
`react-router-dom` cannot be imported by one at all. The hooks that do live in
`hooks/useOverlayRoute.ts`. */

/** Case-insensitive, because react-router matches routes that way. */

/** `/settings`, and `/settings/<anything>`.

Deliberately open-ended: `/settings/:section` is a declared route, and
`sectionFromPath` answers a section that does not exist with the first one, so
a mistyped link opens Settings rather than the not-found page. */
const SETTINGS_PATH = /^\/settings(\/|$)/i;

/** `/friends` exactly, with an optional trailing slash — and nothing below it.

Not the open-ended shape Settings uses, because Friends declares no child
route: `/friends/anything` is in neither the route table nor
`client_routes.py`, so the server answers 404 for it and the client has to
agree. Matching it here drew the working Friends screen over a lobby on a URL
the server had just called non-existent. */
const FRIENDS_PATH_PATTERN = /^\/friends\/?$/i;

export const FRIENDS_PATH = "/friends";

export function isSettingsPath(pathname: string): boolean {
  return SETTINGS_PATH.test(pathname);
}

export function isFriendsPath(pathname: string): boolean {
  return FRIENDS_PATH_PATTERN.test(pathname);
}

/** Whether this path is drawn over another one.

The list, not a flag on each: `App.tsx` has to decide *which location to draw
the page table against* before it knows which overlay is open, and a second
overlay added without touching this would render over nothing at all. */
export function isOverlayPath(pathname: string): boolean {
  return isSettingsPath(pathname) || isFriendsPath(pathname);
}

export interface OverlayLocationState {
  /** The path the overlay was opened from, drawn underneath it until it closes. */
  overlayBackground?: string;
}

/** The page an overlay was opened over, or nothing if it was reached directly.

Nothing is the ordinary case for somebody who followed a link or typed the URL:
they get the lobby behind them, which is what the caller does with a null. */
export function overlayBackgroundOf(state: unknown): string | null {
  if (!state || typeof state !== "object") return null;
  const background = (state as OverlayLocationState).overlayBackground;
  return typeof background === "string" && background ? background : null;
}
